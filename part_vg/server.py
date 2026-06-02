"""
FastAPI surface for the Bifrost web GUI.

Thin layer: spawns Orchestrator in a background thread, streams StateRegistry
snapshots over SSE. No duplicated orchestration logic.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

_HERE = Path(__file__).parent
_POLL_S = 0.25

_run_lock = threading.Lock()
_current: dict[str, Any] | None = None


class RunRequest(BaseModel):
    task: str = Field(min_length=1)
    cap: float | None = None


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
) -> None:
    from cost import CostTracker
    from orchestrator import Orchestrator
    from state import StateRegistry

    try:
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
        )
        holder["result"] = orch.run(task)
    except Exception as e:
        holder["error"] = str(e)
        registry = holder.get("registry")
        if registry is not None:
            registry.set_phase("done")
    finally:
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


@app.get("/api/config")
def api_config() -> dict:
    from config import Config
    from backends import resolve

    config = Config.load(toml_path=str(_HERE / "config.toml"), env_path=str(_HERE / ".env"))
    local_backends, cloud_backend = resolve(config)
    return {
        "cost_cap_usd": config.cost_cap_usd,
        "cost_warning_threshold": config.cost_warning_threshold,
        "comparison_models": config.comparison_models,
        "locals": [
            {"name": b.name, "model": b.model, "is_local": b.is_local}
            for b in local_backends
        ],
        "cloud": {
            "name": cloud_backend.name,
            "model": cloud_backend.model,
            "is_local": cloud_backend.is_local,
        },
        "router_model": config.router_model,
        "compaction_model": config.compaction_model,
    }


@app.post("/api/run")
def api_run(req: RunRequest) -> dict:
    global _current

    with _run_lock:
        if _current is not None and _current.get("running"):
            raise HTTPException(status_code=409, detail="A run is already in progress")

        from config import Config
        from backends import resolve

        config = Config.load(toml_path=str(_HERE / "config.toml"), env_path=str(_HERE / ".env"))
        if req.cap is not None:
            config.cost_cap_usd = req.cap
        Path(config.workspace_dir).mkdir(parents=True, exist_ok=True)

        local_backends, cloud_backend = resolve(config)
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
            daemon=True,
        )
        thread.start()
        holder["thread"] = thread

    return {"run_id": run_id}


@app.post("/api/reset")
def api_reset() -> dict:
    global _current

    with _run_lock:
        if _current is not None and _current.get("running"):
            raise HTTPException(
                status_code=409,
                detail="Cannot reset while a run is in progress",
            )
        _current = None

    script = _HERE / "scripts" / "reset_seed.sh"
    subprocess.run(["bash", str(script)], check=False, cwd=str(_HERE))
    return {"ok": True}


@app.get("/api/events")
async def api_events() -> StreamingResponse:
    from serializer import build_payload

    async def stream():
        while True:
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
                    )
                    if holder.get("error"):
                        payload["error"] = holder["error"]

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


_dist = _HERE / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="frontend")
