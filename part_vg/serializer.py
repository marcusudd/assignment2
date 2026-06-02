"""
Registry + cost snapshots → JSON for the web GUI (SSE).

Pure functions — no LLM calls, unit-testable in isolation.
"""
from __future__ import annotations

import time
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


def _relative_times(states: list[WorkerState]) -> float | None:
    starts = [ws.start_ts for ws in states if ws.start_ts is not None]
    return min(starts) if starts else None


def _workers_overlap(states: list[WorkerState]) -> bool:
    active = [
        (ws.start_ts, ws.end_ts or time.monotonic())
        for ws in states
        if ws.start_ts is not None
    ]
    if len(active) < 2:
        return False
    for i, (a0, a1) in enumerate(active):
        for b0, b1 in active[i + 1 :]:
            if a0 < b1 and b0 < a1:
                return True
    return False


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


def _derive_criteria(
    states: list[WorkerState],
    events: list[dict[str, str]],
    routing_mode: int | None,
    parallel_overlap: bool,
) -> dict[str, bool]:
    log_text = "\n".join(line for ws in states for line in ws.log_lines)
    has_bash = "▶ bash:" in log_text
    has_section_edit = "[section-edit]" in log_text
    has_blocked = any(e["kind"] == "blocked" for e in events)
    has_compaction = any(e["kind"] == "compaction" for e in events)
    has_yield = any(e["kind"] == "done" for e in events) or any(
        ws.status in ("done", "error", "aborted") for ws in states
    )
    parallel = routing_mode == 3 and len(states) >= 2 and parallel_overlap
    return {
        "VG.1": parallel,
        "VG.2": has_compaction,
        "VG.3": True,
        "VG.4": has_blocked,
        "VG.5": has_bash,
        "VG.6": has_section_edit,
        "VG.7": True,
        "VG.8": True,
        "VG.9": has_yield,
    }


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
                "role": ws.role,
                "backend": ws.backend,
                "model": ws.model,
                "status": ws.status,
                "action": ws.current_action,
                "tokens": ws.prompt_tokens + ws.completion_tokens,
                "cost": round(ws.cost_usd, 6),
                "start": start_rel,
                "end": end_rel,
                "is_local": _is_local_backend(ws.backend),
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
    parallel_overlap = _workers_overlap(states)
    criteria = _derive_criteria(states, events, routing_mode, parallel_overlap)

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
        "criteria": criteria,
        "parallel_overlap": parallel_overlap,
    }
