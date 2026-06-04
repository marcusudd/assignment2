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


def _worker_realm(ws: WorkerState) -> str:
    if ws.worker_id.startswith("midgard."):
        return "midgard"
    if ws.worker_id.startswith("asgard."):
        return "asgard"
    if ws.worker_id == "integration":
        return "asgard"
    return "midgard" if _is_local_backend(ws.backend) else "asgard"


def _classify_event(line: str) -> str:
    kind = "action"
    for marker, k in _EVENT_MARKERS.items():
        if marker in line:
            kind = k
            break
    if line.startswith("Done:"):
        kind = "done"
    if line.startswith("🔀") or "Router:" in line:
        kind = "routing"
    if "lane started" in line or line.startswith("▶ [Midgard") or line.startswith("▶ [Asgard"):
        kind = "lane"
    if "Circuit breaker" in line or "output truncated" in line or "Max rounds reached" in line:
        kind = "error"
    if "malformed JSON" in line and "repaired" not in line:
        kind = "error"
    return kind


def _parse_events(
    states: list[WorkerState],
    run_log: list[tuple[float, str]],
    t0: float | None,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    for stamp, line in run_log:
        ts = round(stamp - t0, 2) if t0 is not None else None
        events.append(
            {
                "kind": _classify_event(line),
                "text": line,
                "worker": None,
                "realm": "bifrost",
                "ts": ts,
            }
        )

    for ws in states:
        realm = _worker_realm(ws)
        stamps = ws.log_ts
        for i, line in enumerate(ws.log_lines):
            if i < len(stamps) and t0 is not None:
                ts = round(stamps[i] - t0, 2)
            elif ws.start_ts is not None and t0 is not None:
                ts = round(ws.start_ts - t0 + i * 0.01, 2)
            else:
                ts = None
            events.append(
                {
                    "kind": _classify_event(line),
                    "text": line,
                    "worker": ws.worker_id,
                    "realm": realm,
                    "ts": ts,
                }
            )

    events.sort(key=lambda e: (e["ts"] is None, e.get("ts") or 0))
    return events[-120:]


def _worker_end_rel(
    ws: WorkerState,
    t0: float,
    now_mono: float,
    *,
    live: bool,
    run_end_ts: float | None,
) -> float | None:
    if ws.end_ts is not None:
        return round(ws.end_ts - t0, 2)
    if live and ws.start_ts is not None and ws.status in ("running", "pending"):
        return round(now_mono - t0, 2)
    if ws.start_ts is not None:
        freeze = run_end_ts if run_end_ts is not None else ws.start_ts
        return round(freeze - t0, 2)
    return None


def _extract_tool_evidence(events: list[dict[str, Any]]) -> dict[str, Any]:
    tools: list[dict[str, str]] = []
    blocks: list[dict[str, str]] = []
    for ev in events:
        text = ev.get("text") or ""
        kind = ev.get("kind")
        if kind == "blocked":
            blocks.append({"text": text, "worker": ev.get("worker")})
            continue
        if kind != "action":
            continue
        for name in ("read_file", "write_file", "edit_file", "bash"):
            if name in text:
                tools.append({"tool": name, "text": text, "worker": ev.get("worker")})
                break
    return {
        "tools": tools[-30:],
        "blocks": blocks[-10:],
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
    run_end_ts: float | None = None,
    built: dict[str, list[str]] | None = None,
    log_path: str | None = None,
) -> dict[str, Any]:
    states = registry.snapshot()
    phase = registry.get_phase()
    routing_mode, routing_summary = registry.get_routing()
    t0 = _relative_times(states)

    now_mono = time.monotonic()
    live = running and not cost_tracker.should_stop()
    worker_rows: list[dict[str, Any]] = []
    for ws in sorted(states, key=lambda w: w.worker_id):
        start_rel = None
        end_rel = None
        if ws.start_ts is not None and t0 is not None:
            start_rel = round(ws.start_ts - t0, 2)
        if t0 is not None:
            end_rel = _worker_end_rel(
                ws, t0, now_mono, live=live, run_end_ts=run_end_ts
            )
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
    savings = cost_tracker.savings_breakdown(comparison_models)

    events = _parse_events(states, registry.run_log_snapshot(), t0)

    fallback_detected = "fallback" in routing_summary.lower()
    if routing_mode == 1 and not fallback_detected:
        fallback_detected = any(not w["is_local"] for w in worker_rows)

    by_role: dict[str, int] = {}
    local_count = 0
    cloud_count = 0
    for w in worker_rows:
        by_role[w["role"]] = by_role.get(w["role"], 0) + 1
        if w["is_local"]:
            local_count += 1
        else:
            cloud_count += 1

    ends = [w["end"] for w in worker_rows if w["end"] is not None]
    span_sec = round(max(ends), 2) if ends else 0.0

    created = (built or {}).get("created") or []
    modified = (built or {}).get("modified") or []
    evidence = _extract_tool_evidence(events)

    payload: dict[str, Any] = {
        "run_id": run_id,
        "task": task,
        "running": running,
        "result": result,
        "phase": phase,
        "routing": {
            "mode": routing_mode,
            "summary": routing_summary,
            "reasoning": _routing_reasoning(routing_summary),
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
        "metrics": {
            "span_sec": span_sec,
            "span_live": live,
            "workers": {
                "total": len(worker_rows),
                "local": local_count,
                "cloud": cloud_count,
                "by_role": by_role,
            },
        },
        "evidence": evidence,
    }
    if built is not None:
        payload["built"] = {"created": created, "modified": modified}
    if log_path:
        payload["log_path"] = log_path
    if not running and phase == "done":
        payload["run_summary"] = {
            "workers": len(worker_rows),
            "span_sec": span_sec,
            "cost_usd": round(snap["total_usd"], 6),
            "cap_usd": snap["cap_usd"],
            "stopped": cost_tracker.should_stop(),
            "warning": cost_tracker.is_warning(),
            "files_created": len(created),
            "files_modified": len(modified),
        }
    return payload


def _routing_reasoning(summary: str) -> str:
    """Parse short router reasoning from orchestrator summary line."""
    if not summary:
        return ""
    if summary.startswith("Mode "):
        rest = summary.split(": ", 1)
        if len(rest) < 2:
            return summary
        tail = rest[1]
        if " (" in tail:
            return tail.rsplit(" (", 1)[0].strip()
        return tail.strip()
    return summary
