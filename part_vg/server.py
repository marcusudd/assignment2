"""
FastAPI surface for the Bifrost web GUI.

Thin layer: spawns Orchestrator in a background thread, streams StateRegistry
snapshots over SSE. No duplicated orchestration logic.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from preflight import run_preflight
from session_log import (
    LOG_DIR,
    Tee,
    list_log_files,
    open_session_log,
    read_log_tail,
    write_session_summary,
)
from workspace_diff import diff_workspace, snapshot_workspace

_HERE = Path(__file__).parent
_POLL_S = 0.25
_MOCK_SSE = os.environ.get("BIFROST_MOCK", "").lower() in ("1", "true", "yes")
_MOCK_FIXTURE_PATH = _HERE / "fixtures" / "mock-payload.json"

_run_lock = threading.Lock()
_current: dict[str, Any] | None = None

LOG_DIR.mkdir(parents=True, exist_ok=True)
_server_log = logging.FileHandler(LOG_DIR / "server.log", encoding="utf-8")
_server_log.setFormatter(
    logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
)
logging.getLogger().addHandler(_server_log)
logging.getLogger().setLevel(logging.INFO)


class RunRequest(BaseModel):
    task: str = Field(min_length=1)
    cap: float | None = None
    allow_local: bool = True
    allow_cloud: bool = True


def _load_system_prompt(config) -> str:
    path = _HERE / "config" / "system_prompt.txt"
    text = path.read_text(encoding="utf-8")
    return (
        text.replace("{workspace_dir}", str(Path(config.workspace_dir).resolve()))
        .replace("{max_output}", str(config.max_output))
        .replace("{python_cmd}", "python3")
    )


def _idle_payload() -> dict:
    from config import Config
    from cost import CostTracker
    from state import StateRegistry
    from serializer import build_payload

    try:
        config = Config.load(toml_path=str(_HERE / "config.toml"), env_path=str(_HERE / ".env"))
        cap = config.cost_cap_usd
        comparison = config.comparison_models
    except Exception:
        cap = 0.20
        comparison = []

    registry = StateRegistry()
    cost = CostTracker(cap_usd=cap, prices_path=str(_HERE / "model_prices.json"))
    return build_payload(registry, cost, comparison_models=comparison)


def _run_orchestrator(
    task: str,
    config,
    local_backends,
    cloud_backend,
    system_prompt: str,
    holder: dict[str, Any],
    *,
    allow_local: bool = True,
    allow_cloud: bool = True,
) -> None:
    from cost import CostTracker
    from orchestrator import Orchestrator
    from state import StateRegistry

    log_fh = None
    real_stderr = sys.stderr
    orch = None
    before_files: dict[str, float] = {}
    try:
        before_files = snapshot_workspace(config.workspace_dir)
        log_path, log_fh = open_session_log(task, run_id=holder.get("run_id"))
        holder["log_path"] = str(log_path)
        sys.stderr = Tee(real_stderr, log_fh)  # type: ignore[assignment]
        logging.info("Run %s started — log %s", holder.get("run_id"), log_path)

        prices_path = _HERE / "model_prices.json"
        cost_tracker = CostTracker(
            cap_usd=config.cost_cap_usd,
            warning_threshold=config.cost_warning_threshold,
            prices_path=str(prices_path),
        )
        registry = StateRegistry()
        holder["registry"] = registry
        holder["cost_tracker"] = cost_tracker

        orch = Orchestrator(
            config=config,
            local_backends=local_backends,
            cloud_backend=cloud_backend,
            cost_tracker=cost_tracker,
            registry=registry,
            worker_system_prompt=system_prompt,
            allow_local=allow_local,
            allow_cloud=allow_cloud,
        )
        holder["result"] = orch.run(task)
    except Exception as e:
        holder["error"] = str(e)
        logging.exception("Run %s failed", holder.get("run_id"))
        registry = holder.get("registry")
        if registry is not None:
            registry.set_phase("done")
    finally:
        created, modified = diff_workspace(
            before_files, snapshot_workspace(config.workspace_dir)
        )
        holder["built"] = {"created": created, "modified": modified}
        registry = holder.get("registry")
        cost_tracker = holder.get("cost_tracker")
        if log_fh is not None and registry is not None and cost_tracker is not None:
            snap = cost_tracker.snapshot()
            built_tuple = None
            built = holder.get("built")
            if built:
                built_tuple = (built.get("created", []), built.get("modified", []))
            write_session_summary(
                log_fh,
                task=task,
                result=holder.get("result"),
                snap=snap,
                registry=registry,
                routing=orch.routing_summary if orch else "",
                error=holder.get("error"),
                built=built_tuple,
            )
        if log_fh is not None:
            sys.stderr = real_stderr
            log_fh.close()
            logging.info("Run %s finished — log %s", holder.get("run_id"), holder.get("log_path"))
        holder["run_end_ts"] = time.monotonic()
        holder["running"] = False


app = FastAPI(title="Bifrost")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def api_health() -> dict:
    return {"ok": True, "service": "bifrost"}


@app.get("/api/logs")
def api_logs() -> dict:
    """List recent session log files (newest first)."""
    return {"dir": str(LOG_DIR.resolve()), "files": list_log_files()}


@app.get("/api/logs/{filename}")
def api_log_tail(filename: str, lines: int = 200) -> dict:
    """Tail of a session log for debugging."""
    try:
        body = read_log_tail(filename, max_lines=min(lines, 500))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Log not found") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"name": filename, "tail": body}


@app.get("/api/preflight")
def api_preflight() -> dict:
    if _MOCK_SSE:
        return {
            "ready": True,
            "checks": [{"id": "mock", "label": "Mock mode", "ok": True, "detail": "BIFROST_MOCK", "critical": False}],
        }
    return run_preflight(
        toml_path=_HERE / "config.toml",
        env_path=_HERE / ".env",
        api_base="http://127.0.0.1:8000",
    )


@app.get("/api/config")
def api_config() -> dict:
    from config import Config
    from backends import resolve
    from llm import health_check, list_models

    config = Config.load(toml_path=str(_HERE / "config.toml"), env_path=str(_HERE / ".env"))
    local_backends, cloud_backend = resolve(config)
    served: set[str] = set()
    if config.locals:
        served = set(
            list_models(config.locals[0].base_url, config.locals[0].api_key)
        )
    locals_out = []
    for bc in config.locals:
        locals_out.append(
            {
                "name": bc.name,
                "model": bc.model,
                "is_local": True,
                "loaded": bc.model in served,
            }
        )
    return {
        "cost_cap_usd": config.cost_cap_usd,
        "cost_warning_threshold": config.cost_warning_threshold,
        "comparison_models": config.comparison_models,
        "served_models": sorted(served),
        "locals": locals_out,
        "cloud": {
            "name": cloud_backend.name,
            "model": cloud_backend.model,
            "is_local": cloud_backend.is_local,
        },
        "router_model": config.router_model,
        "compaction_model": config.compaction_model,
        "openrouter_configured": bool(config.openrouter_api_key),
        "lm_studio_reachable": bool(served) or health_check(
            config.locals[0].base_url, config.locals[0].api_key
        )
        if config.locals
        else False,
    }


@app.post("/api/run")
def api_run(req: RunRequest) -> dict:
    global _current

    if _MOCK_SSE:
        return {"run_id": "mock01"}

    with _run_lock:
        if _current is not None and _current.get("running"):
            raise HTTPException(status_code=409, detail="A run is already in progress")

        from config import Config
        from backends import resolve

        config = Config.load(toml_path=str(_HERE / "config.toml"), env_path=str(_HERE / ".env"))
        if req.cap is not None:
            config.cost_cap_usd = req.cap
        if not req.allow_local and not req.allow_cloud:
            raise HTTPException(
                status_code=400,
                detail="At least one realm (Midgard or Asgard) must be enabled",
            )
        Path(config.workspace_dir).mkdir(parents=True, exist_ok=True)

        local_backends, cloud_backend = resolve(config)
        if not req.allow_cloud and not any(b.is_local for b in local_backends):
            raise HTTPException(
                status_code=400,
                detail="Asgard disabled but no local models loaded in LM Studio",
            )
        system_prompt = _load_system_prompt(config)
        run_id = str(uuid.uuid4())[:8]

        holder: dict[str, Any] = {
            "run_id": run_id,
            "task": req.task,
            "running": True,
            "result": None,
            "error": None,
            "registry": None,
            "cost_tracker": None,
            "comparison_models": config.comparison_models,
        }
        _current = holder

        thread = threading.Thread(
            target=_run_orchestrator,
            args=(req.task, config, local_backends, cloud_backend, system_prompt, holder),
            kwargs={
                "allow_local": req.allow_local,
                "allow_cloud": req.allow_cloud,
            },
            daemon=True,
        )
        thread.start()
        holder["thread"] = thread

    return {"run_id": run_id}


@app.post("/api/compact")
def api_compact() -> dict:
    if _MOCK_SSE:
        return {"ok": True}

    with _run_lock:
        holder = _current
    if holder is None or not holder.get("running"):
        raise HTTPException(status_code=400, detail="No active run to compact")
    registry = holder.get("registry")
    if registry is None:
        raise HTTPException(status_code=400, detail="Registry not ready")
    registry.request_compact()
    return {"ok": True}


@app.post("/api/reset")
def api_reset() -> dict:
    global _current

    if _MOCK_SSE:
        return {"ok": True}

    with _run_lock:
        if _current is not None and _current.get("running"):
            raise HTTPException(
                status_code=409,
                detail="Cannot reset while a run is in progress",
            )
        _current = None

    script = _HERE / "scripts" / "clear_workspace.sh"
    subprocess.run(["bash", str(script)], check=False, cwd=str(_HERE))
    return {"ok": True}


def _load_mock_fixture() -> dict:
    data = json.loads(_MOCK_FIXTURE_PATH.read_text(encoding="utf-8"))
    if not data.get("running"):
        return data
    workers = data.get("workers") or []
    for w in workers:
        if w.get("end") is not None:
            w["end"] = round(w["end"] + 0.25, 2)
    if workers:
        span = max(w.get("end") or 0 for w in workers)
        metrics = data.setdefault("metrics", {})
        metrics["span_sec"] = span
        metrics["span_live"] = True
    return data


@app.get("/api/events")
async def api_events() -> StreamingResponse:
    from serializer import build_payload

    async def stream():
        while True:
            if _MOCK_SSE and _MOCK_FIXTURE_PATH.is_file():
                payload = _load_mock_fixture()
            else:
                with _run_lock:
                    holder = _current

                if holder is None:
                    payload = _idle_payload()
                else:
                    registry = holder.get("registry")
                    cost = holder.get("cost_tracker")
                    if registry is None or cost is None:
                        payload = _idle_payload()
                        payload["task"] = holder.get("task", "")
                        payload["run_id"] = holder.get("run_id")
                        payload["running"] = holder.get("running", False)
                    else:
                        payload = build_payload(
                            registry,
                            cost,
                            holder.get("comparison_models", []),
                            task=holder.get("task", ""),
                            run_id=holder.get("run_id"),
                            result=holder.get("result"),
                            running=holder.get("running", False),
                            run_end_ts=holder.get("run_end_ts"),
                            built=holder.get("built"),
                            log_path=holder.get("log_path"),
                        )
                    if holder.get("error"):
                        payload["error"] = holder["error"]
                    elif holder.get("log_path") and "log_path" not in payload:
                        payload["log_path"] = holder["log_path"]

            yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(_POLL_S)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


_frontend_public = _HERE / "frontend" / "public"
_dist = _HERE / "frontend" / "dist"


def _frontend_asset(name: str) -> Path | None:
    """Favicon etc. — prefer built dist, fall back to public/ (dev without rebuild)."""
    for base in (_dist, _frontend_public):
        path = base / name
        if path.is_file():
            return path
    return None


@app.get("/favicon.svg", include_in_schema=False)
async def favicon_svg() -> FileResponse:
    path = _frontend_asset("favicon.svg")
    if path is None:
        raise HTTPException(status_code=404, detail="favicon not found")
    return FileResponse(path, media_type="image/svg+xml")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon_ico() -> FileResponse:
    path = _frontend_asset("favicon.ico")
    if path is not None:
        return FileResponse(path, media_type="image/x-icon")
    svg = _frontend_asset("favicon.svg")
    if svg is None:
        raise HTTPException(status_code=404, detail="favicon not found")
    return FileResponse(svg, media_type="image/svg+xml")


@app.get("/apple-touch-icon.png", include_in_schema=False)
async def apple_touch_icon() -> FileResponse:
    path = _frontend_asset("apple-touch-icon.png")
    if path is None:
        raise HTTPException(status_code=404, detail="apple-touch-icon not found")
    return FileResponse(path, media_type="image/png")


if _dist.is_dir():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="frontend")
