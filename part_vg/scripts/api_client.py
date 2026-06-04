"""
HTTP helpers for terminal runs via FastAPI — same surface as the web GUI.
"""
from __future__ import annotations

import json
import sys
import time
from typing import Any, Callable

import httpx

DEFAULT_BASE = "http://127.0.0.1:8000"


def parse_sse_line(line: str) -> dict | None:
    if not line.startswith("data: "):
        return None
    return json.loads(line[6:])


def stream_run(
    client: httpx.Client,
    run_id: str,
    *,
    on_payload: Callable[[dict], None] | None = None,
    timeout_s: float | None = None,
) -> dict:
    """Subscribe to /api/events until run_id finishes (phase done, not running)."""
    deadline = time.monotonic() + timeout_s if timeout_s else None
    last: dict = {}
    with client.stream("GET", "/api/events", timeout=None) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if deadline is not None and time.monotonic() > deadline:
                raise TimeoutError(f"run {run_id} timed out after {timeout_s}s")
            payload = parse_sse_line(line)
            if payload is None:
                continue
            if payload.get("run_id") != run_id:
                continue
            last = payload
            if on_payload:
                on_payload(payload)
            if not payload.get("running") and payload.get("phase") == "done":
                return payload
    return last


def post_run(
    client: httpx.Client,
    task: str,
    *,
    cap: float | None = None,
    allow_local: bool = True,
    allow_cloud: bool = True,
) -> str:
    body: dict[str, Any] = {
        "task": task,
        "allow_local": allow_local,
        "allow_cloud": allow_cloud,
    }
    if cap is not None:
        body["cap"] = cap
    r = client.post("/api/run", json=body)
    if r.status_code == 409:
        raise RuntimeError("409: a run is already in progress — wait or refresh GUI")
    r.raise_for_status()
    return r.json()["run_id"]


def print_run_progress(payload: dict, *, last_phase: str | None = None) -> str | None:
    """Compact terminal progress line; returns new phase if changed."""
    phase = payload.get("phase") or "…"
    routing = payload.get("routing") or {}
    mode = routing.get("mode")
    metrics = payload.get("metrics") or {}
    wm = metrics.get("workers") or {}
    cost = payload.get("cost") or {}
    line = (
        f"\r  [{phase}]"
        f" mode={mode}"
        f" workers={wm.get('total', 0)}"
        f" ({wm.get('local', 0)}L/{wm.get('cloud', 0)}C)"
        f" ${cost.get('total', 0):.4f}/${cost.get('cap', 0):.2f}"
    )
    if cost.get("warning"):
        line += " ⚠"
    if cost.get("stopped"):
        line += " STOP"
    sys.stdout.write(line)
    sys.stdout.flush()
    if phase != last_phase:
        return phase
    return last_phase


def print_run_result(payload: dict) -> None:
    print()
    routing = payload.get("routing") or {}
    print(f"Routing: {routing.get('summary', '')}")
    cost = payload.get("cost") or {}
    print(f"Cost: ${cost.get('total', 0):.4f} / ${cost.get('cap', 0):.2f}")
    if cost.get("stopped"):
        print("Budget cap stopped the run.")

    built = payload.get("built") or {}
    created = built.get("created") or []
    modified = built.get("modified") or []
    print("\nBuilt:")
    if not created and not modified:
        print("  (no file changes)")
    for f in created:
        print(f"  + {f}")
    for f in modified:
        print(f"  ~ {f}")

    summary = payload.get("run_summary") or {}
    if summary:
        print(
            f"\nSummary: {summary.get('workers', 0)} workers · "
            f"{summary.get('span_sec', 0):.1f}s · "
            f"${summary.get('cost_usd', 0):.4f}"
        )

    if payload.get("error"):
        print(f"\nError: {payload['error']}")
    if payload.get("result"):
        text = str(payload["result"])
        print("\nResult:")
        print(text[:2000] + ("…" if len(text) > 2000 else ""))
    if payload.get("log_path"):
        print(f"\nLog: {payload['log_path']}")
