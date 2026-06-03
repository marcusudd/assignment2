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
            worker_id="midgard.models-x",
            role="coder",
            task_summary="write models",
            backend="local-0",
            model="gemma-test",
            status="running",
            start_ts=t0,
            current_action="gemma: creating models/x.py",
            prompt_tokens=100,
            completion_tokens=50,
            cost_usd=0.0,
            owned_files=["models/x.py"],
        )
    )
    registry.set_routing(3, "Mode 3: parallel (4 workers)")
    registry.set_phase("fanout")

    cost = _tracker()
    payload = build_payload(registry, cost, ["anthropic/claude-opus-4-8"])

    assert payload["phase"] == "fanout"
    assert payload["routing"]["mode"] == 3
    assert len(payload["workers"]) == 1
    assert payload["workers"][0]["id"] == "midgard.models-x"
    assert payload["workers"][0]["label"] == "Midgard · models/x.py"
    assert payload["workers"][0]["tokens"] == 150
    assert payload["workers"][0]["is_local"] is True
    assert payload["workers"][0]["start"] == 0.0
    assert payload["cost"]["cap"] == 1.0
    assert payload["metrics"]["workers"]["local"] == 1
    assert payload["metrics"]["span_live"] is False


def test_events_from_log_markers():
    registry = StateRegistry()
    ws = WorkerState(
        worker_id="asgard.primary",
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
    assert all("ts" in e for e in payload["events"])


def test_events_include_timestamps_when_stamps_present():
    registry = StateRegistry()
    t0 = time.monotonic()
    ws = WorkerState(
        worker_id="midgard.models-x",
        role="coder",
        task_summary="x",
        backend="local-0",
        model="m",
        start_ts=t0,
    )
    ws.log_lines = ["▶ bash: ls"]
    ws.log_ts = [t0 + 0.5]
    registry.register(ws)
    registry.append_run_log("🔀 Router: Mode 1 test")
    payload = build_payload(registry, _tracker(), [])
    assert payload["events"][0]["kind"] == "routing"
    assert payload["events"][0]["realm"] == "bifrost"
    assert payload["events"][-1]["ts"] == 0.5


def test_fallback_detected_from_routing_summary():
    registry = StateRegistry()
    registry.register(
        WorkerState(
            worker_id="asgard.primary",
            role="coder",
            task_summary="x",
            backend="cloud",
            model="anthropic/claude-haiku-4-5",
            status="running",
        )
    )
    registry.set_routing(
        2,
        "Mode 2: Fallback: single cloud worker (decomposition unavailable)",
    )
    payload = build_payload(registry, _tracker(), [])
    assert payload["fallback_detected"] is True


def test_running_worker_gets_live_end():
    registry = StateRegistry()
    t0 = time.monotonic()
    registry.register(
        WorkerState(
            worker_id="midgard.models-x",
            role="coder",
            task_summary="x",
            backend="cloud",
            model="m",
            status="running",
            start_ts=t0,
        )
    )
    payload = build_payload(registry, _tracker(), [], running=True)
    assert payload["workers"][0]["end"] is not None
    assert payload["workers"][0]["end"] >= payload["workers"][0]["start"]
    assert payload["metrics"]["span_live"] is True


def test_frozen_span_when_run_not_live():
    registry = StateRegistry()
    t0 = time.monotonic()
    run_end = t0 + 5.0
    registry.register(
        WorkerState(
            worker_id="midgard.models-x",
            role="coder",
            task_summary="x",
            backend="local-0",
            model="m",
            status="running",
            start_ts=t0,
        )
    )
    payload_a = build_payload(
        registry, _tracker(), [], running=False, run_end_ts=run_end
    )
    time.sleep(0.05)
    payload_b = build_payload(
        registry, _tracker(), [], running=False, run_end_ts=run_end
    )
    assert payload_a["metrics"]["span_live"] is False
    assert payload_a["metrics"]["span_sec"] == payload_b["metrics"]["span_sec"]
    assert payload_a["workers"][0]["end"] == payload_b["workers"][0]["end"]


def test_span_live_false_when_cost_cap_stopped():
    registry = StateRegistry()
    t0 = time.monotonic()
    registry.register(
        WorkerState(
            worker_id="midgard.models-x",
            role="coder",
            task_summary="x",
            backend="local-0",
            model="m",
            status="running",
            start_ts=t0,
        )
    )
    cost = _tracker(cap=0.001)
    cost.total_usd = 0.002
    cost._stop_event.set()
    payload = build_payload(registry, cost, [], running=True)
    assert payload["cost"]["stopped"] is True
    assert payload["metrics"]["span_live"] is False
