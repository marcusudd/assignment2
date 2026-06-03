"""
Registry + cost snapshots → JSON for the web GUI (SSE).

Pure functions — no LLM calls, unit-testable in isolation.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from cost import CostTracker
from state import StateRegistry, WorkerState

_EVENT_MARKERS: dict[str, str] = {
    "▶": "action",
    "← BLOCKED": "blocked",
    "🗜": "compaction",
    "⚡": "escalation",
}


def _is_local_backend(backend: str) -> bool:
    return "local" in backend.lower()


def _worker_display_label(ws: WorkerState) -> str:
    """Human-facing lane name; worker_id is realm.file-slug (e.g. midgard.models-order)."""
    if ws.worker_id in ("integration", "asgard.integration"):
        return "Integration"
    if ws.owned_files:
        primary = ws.owned_files[0]
        parts = Path(primary).parts
        short = "/".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
        realm = "Midgard" if _is_local_backend(ws.backend) else "Asgard"
        return f"{realm} · {short}"
    task = (ws.task_summary or "").strip()
    if len(task) > 28:
        task = task[:25] + "…"
    if task:
        return f"{ws.role} · {task}"
    return ws.worker_id


def _relative_times(states: list[WorkerState]) -> float | None:
    starts = [ws.start_ts for ws in states if ws.start_ts is not None]
    return min(starts) if starts else None


def _parse_events(states: list[WorkerState]) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    for ws in states:
        for line in ws.log_lines:
            kind = "action"
            for marker, k in _EVENT_MARKERS.items():
                if marker in line:
                    kind = k
                    break
            if line.startswith("Done:"):
                kind = "done"
            events.append({"kind": kind, "text": line, "worker": ws.worker_id})
    return events[-100:]


def build_payload(
    registry: StateRegistry,
    cost_tracker: CostTracker,
    comparison_models: list[str],
    *,
    task: str = "",
    run_id: str | None = None,
    result: str | None = None,
    running: bool = False,
) -> dict[str, Any]:
    states = registry.snapshot()
    phase = registry.get_phase()
    routing_mode, routing_summary = registry.get_routing()
    t0 = _relative_times(states)

    now_mono = time.monotonic()
    worker_rows: list[dict[str, Any]] = []
    for ws in sorted(states, key=lambda w: w.worker_id):
        start_rel = None
        end_rel = None
        if ws.start_ts is not None and t0 is not None:
            start_rel = round(ws.start_ts - t0, 2)
        if t0 is not None:
            if ws.end_ts is not None:
                end_rel = round(ws.end_ts - t0, 2)
            elif ws.start_ts is not None and ws.status in ("running", "pending"):
                end_rel = round(now_mono - t0, 2)
        worker_rows.append(
            {
                "id": ws.worker_id,
                "label": _worker_display_label(ws),
                "role": ws.role,
                "task_summary": ws.task_summary,
                "owned_files": ws.owned_files,
                "backend": ws.backend,
                "model": ws.model,
                "status": ws.status,
                "action": ws.current_action,
                "tokens": ws.prompt_tokens + ws.completion_tokens,
                "prompt_tokens": ws.prompt_tokens,
                "completion_tokens": ws.completion_tokens,
                "cost": round(ws.cost_usd, 6),
                "start": start_rel,
                "end": end_rel,
                "is_local": _is_local_backend(ws.backend),
                "log_count": len(ws.log_lines),
            }
        )

    snap = cost_tracker.snapshot()
    counterfactual = cost_tracker.counterfactual(comparison_models)
    savings = [
        {
            "model": model,
            "would_cost": round(cost, 6),
            "saved": round(cost - snap["total_usd"], 6),
        }
        for model, cost in sorted(counterfactual.items(), key=lambda x: -x[1])
    ]

    events = _parse_events(states)

    fallback_detected = False
    if routing_mode == 1:
        fallback_detected = any(not w["is_local"] for w in worker_rows)

    return {
        "run_id": run_id,
        "task": task,
        "running": running,
        "result": result,
        "phase": phase,
        "routing": {
            "mode": routing_mode,
            "summary": routing_summary,
        },
        "workers": worker_rows,
        "cost": {
            "total": round(snap["total_usd"], 6),
            "cap": snap["cap_usd"],
            "fraction": round(snap["fraction"], 4),
            "warning": cost_tracker.is_warning(),
            "stopped": cost_tracker.should_stop(),
        },
        "savings": savings,
        "events": events,
        "fallback_detected": fallback_detected,
    }
