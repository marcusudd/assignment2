"""Unit tests for serializer.build_payload — no LLM calls."""
import time

from cost import CostTracker
from serializer import build_payload
from state import StateRegistry, WorkerState


def _tracker(cap: float = 1.0) -> CostTracker:
    return CostTracker(
        cap_usd=cap,
        warning_threshold=0.75,
        prices_path="model_prices.json",
    )


def test_build_payload_workers_and_cost():
    registry = StateRegistry()
    t0 = time.monotonic()
    registry.register(
        WorkerState(
            worker_id="w1",
            role="coder",
            task_summary="write models",
            backend="local-0",
            model="gemma-test",
            status="running",
            start_ts=t0,
            current_action="gemma: creating models/x.py",
            prompt_tokens=100,
            cost_usd=0.0,
        )
    )
    registry.set_routing(3, "Mode 3: parallel (4 workers)")
    registry.set_phase("fanout")

    cost = _tracker()
    payload = build_payload(registry, cost, ["anthropic/claude-opus-4-8"])

    assert payload["phase"] == "fanout"
    assert payload["routing"]["mode"] == 3
    assert len(payload["workers"]) == 1
    assert payload["workers"][0]["id"] == "w1"
    assert payload["workers"][0]["is_local"] is True
    assert payload["workers"][0]["start"] == 0.0
    assert payload["cost"]["cap"] == 1.0
    assert "VG.7" in payload["criteria"]
    assert payload["criteria"]["VG.7"] is True
    assert payload["criteria"]["VG.8"] is True


def test_parallel_criteria_vg1():
    registry = StateRegistry()
    registry.set_routing(3, "Mode 3")
    t0 = time.monotonic()
    for wid in ("w1", "w2"):
        registry.register(
            WorkerState(
                worker_id=wid,
                role="coder",
                task_summary="task",
                backend="cloud",
                model="anthropic/claude-sonnet-4-6",
                status="running",
                start_ts=t0,
                end_ts=t0 + 5.0,
            )
        )

    payload = build_payload(registry, _tracker(), [])
    assert payload["criteria"]["VG.1"] is True


def test_events_from_log_markers():
    registry = StateRegistry()
    ws = WorkerState(
        worker_id="w1",
        role="coder",
        task_summary="x",
        backend="cloud",
        model="m",
    )
    ws.log_lines = [
        "▶ bash: rm -rf /",
        "← BLOCKED (recursive delete). Revise and try again.",
        "🗜 compacted history (context engineering)",
        "⚡ Escalated to cloud",
    ]
    registry.register(ws)

    payload = build_payload(registry, _tracker(), [])
    kinds = {e["kind"] for e in payload["events"]}
    assert "action" in kinds
    assert "blocked" in kinds
    assert "compaction" in kinds
    assert "escalation" in kinds
    assert payload["criteria"]["VG.4"] is True
    assert payload["criteria"]["VG.2"] is True
    assert payload["criteria"]["VG.5"] is True


def test_running_worker_gets_live_end():
    registry = StateRegistry()
    t0 = time.monotonic()
    registry.register(
        WorkerState(
            worker_id="w1",
            role="coder",
            task_summary="x",
            backend="cloud",
            model="m",
            status="running",
            start_ts=t0,
        )
    )
    payload = build_payload(registry, _tracker(), [])
    assert payload["workers"][0]["end"] is not None
    assert payload["workers"][0]["end"] >= payload["workers"][0]["start"]


def test_section_edit_criteria_vg6():
    registry = StateRegistry()
    ws = WorkerState(
        worker_id="w1",
        role="coder",
        task_summary="x",
        backend="cloud",
        model="m",
    )
    ws.log_lines = ["▶ edit_file: routers/x.py [section-edit]"]
    registry.register(ws)

    payload = build_payload(registry, _tracker(), [])
    assert payload["criteria"]["VG.6"] is True
