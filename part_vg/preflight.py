"""
Demo readiness checks — shared by /api/preflight and terminal runners.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from llm import health_check, list_models


def run_preflight(
    *,
    toml_path: str | Path,
    env_path: str | Path,
    api_base: str = "http://127.0.0.1:8000",
) -> dict[str, Any]:
    """Return structured checks for GUI/terminal preflight panels."""
    toml_path = Path(toml_path)
    env_path = Path(env_path)
    checks: list[dict[str, Any]] = []

    def add(
        item_id: str,
        label: str,
        ok: bool,
        detail: str,
        *,
        critical: bool = True,
    ) -> None:
        checks.append(
            {
                "id": item_id,
                "label": label,
                "ok": ok,
                "detail": detail,
                "critical": critical,
            }
        )

    env_exists = env_path.is_file()
    add("env_file", ".env present", env_exists, str(env_path.resolve()) if env_exists else "Copy .env.example → .env")

    if env_exists:
        from dotenv import load_dotenv

        load_dotenv(env_path)

    or_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    add(
        "openrouter_key",
        "OpenRouter API key",
        bool(or_key),
        "configured via .env" if or_key else "Set OPENROUTER_API_KEY in .env",
    )

    config = None
    config_error = None
    if env_exists:
        try:
            from config import Config

            config = Config.load(toml_path=str(toml_path), env_path=str(env_path))
        except Exception as e:
            config_error = str(e)

    if config is None:
        add("config", "config.toml + .env", False, config_error or "Could not load config")
        ready = all(c["ok"] for c in checks if c["critical"])
        return {"ready": ready, "checks": checks, "cap_usd": None, "workspace_dir": None}

    add("config", "Config loaded", True, f"cap ${config.cost_cap_usd:.2f} · warning {int(config.cost_warning_threshold * 100)}%")

    ws = Path(config.workspace_dir)
    ws_ok = ws.is_dir()
    add("workspace", "Workspace directory", ws_ok, str(ws.resolve()) if ws_ok else f"Missing: {ws}")

    local_url = config.locals[0].base_url if config.locals else ""
    local_reachable = False
    served: list[str] = []
    if local_url:
        local_reachable = health_check(local_url, config.locals[0].api_key)
        if local_reachable:
            try:
                served = list_models(local_url, config.locals[0].api_key)
            except Exception:
                served = []

    add(
        "lm_studio",
        "LM Studio reachable",
        local_reachable,
        local_url or "No LOCAL_BASE_URL",
        critical=False,
    )

    for bc in config.locals:
        loaded = bc.model in served
        add(
            f"local_model_{bc.name}",
            f"Local model {bc.name}",
            loaded,
            f"{bc.model} — {'loaded' if loaded else 'not loaded in LM Studio'}",
            critical=False,
        )

    add(
        "cloud_model",
        "Cloud model configured",
        bool(config.cloud.model),
        config.cloud.model,
        critical=False,
    )

    try:
        import httpx

        r = httpx.get(f"{api_base.rstrip('/')}/api/health", timeout=2.0)
        api_ok = r.status_code == 200
    except Exception:
        api_ok = False

    add(
        "api",
        "Bifrost API (GUI backend)",
        api_ok,
        f"{api_base}/api/health" if api_ok else f"Start server: uvicorn server:app --port 8000",
        critical=False,
    )

    ready = all(c["ok"] for c in checks if c["critical"])
    return {
        "ready": ready,
        "checks": checks,
        "cap_usd": config.cost_cap_usd,
        "cost_warning_threshold": config.cost_warning_threshold,
        "workspace_dir": str(ws.resolve()) if ws_ok else str(ws),
        "local_models": [l.model for l in config.locals],
        "cloud_model": config.cloud.model,
    }
