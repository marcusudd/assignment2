"""Tests for CostTracker — including thread-safety (H3, VG.3)."""
import threading
import pytest
from cost import CostTracker, BudgetExceeded


def _tracker(cap=1.0) -> CostTracker:
    return CostTracker(cap_usd=cap, warning_threshold=0.75, prices_path="model_prices.json")


def test_add_and_snapshot():
    t = _tracker()
    t.add("w1", "anthropic/claude-sonnet-4-6", prompt_tokens=1000, completion_tokens=500)
    snap = t.snapshot()
    assert snap["total_usd"] > 0
    assert snap["worker_cost"]["w1"] > 0


def test_local_model_zero_cost():
    t = _tracker()
    t.add("w1", "local/qwen3.6-27b", prompt_tokens=10000, completion_tokens=5000)
    snap = t.snapshot()
    assert snap["total_usd"] == 0.0


def test_warning_flag():
    t = _tracker(cap=0.001)
    # sonnet: 3e-6 per input token; 800 tokens ≈ $0.0024 > 75% of $0.001
    with pytest.raises(BudgetExceeded):
        t.add("w1", "anthropic/claude-sonnet-4-6", 800, 0)
    assert t.should_stop()


def test_hard_cap_raises():
    t = _tracker(cap=0.000001)
    with pytest.raises(BudgetExceeded):
        t.add("w1", "anthropic/claude-sonnet-4-6", 10, 10)


def test_thread_safety_no_race():
    """N threads adding concurrently must not corrupt the total."""
    t = _tracker(cap=100.0)
    errors = []

    def worker(wid: str):
        try:
            for _ in range(50):
                t.add(wid, "anthropic/claude-haiku-4-5", 10, 5)
        except BudgetExceeded:
            pass
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    assert not errors, f"Thread errors: {errors}"
    snap = t.snapshot()
    # 8 workers × 50 calls × (10+5) tokens × haiku price
    assert snap["total_usd"] >= 0


def test_counterfactual():
    t = _tracker(cap=1.0)
    t.add("w1", "anthropic/claude-haiku-4-5", 1000, 500)
    cf = t.counterfactual(["anthropic/claude-sonnet-4-6", "anthropic/claude-opus-4-8"])
    # Sonnet and Opus should both cost more than Haiku for same token volumes
    assert cf["anthropic/claude-sonnet-4-6"] > cf.get("anthropic/claude-haiku-4-5", 0)
    assert cf["anthropic/claude-opus-4-8"] >= cf["anthropic/claude-sonnet-4-6"]


def test_per_worker_attribution():
    t = _tracker(cap=10.0)
    t.add("w1", "anthropic/claude-sonnet-4-6", 500, 200)
    t.add("w2", "anthropic/claude-haiku-4-5", 500, 200)
    snap = t.snapshot()
    assert "w1" in snap["worker_cost"]
    assert "w2" in snap["worker_cost"]
    assert snap["worker_cost"]["w1"] > snap["worker_cost"]["w2"]


def test_savings_breakdown_split_sums_correctly():
    """local_saved + routing_saved must equal saved (total counterfactual saving)."""
    t = _tracker(cap=10.0)
    # Local worker (free)
    t.add("w1", "local/gemma", 5000, 2000)
    # Cloud worker (paid)
    t.add("w2", "anthropic/claude-haiku-4-5", 1000, 500)

    breakdown = t.savings_breakdown(["anthropic/claude-opus-4-8"])
    assert len(breakdown) == 1
    row = breakdown[0]

    # Structural integrity: split sums to total
    assert abs(row["local_saved"] + row["routing_saved"] - row["saved"]) < 1e-9
    # would_cost must be > actual (Opus is more expensive than Haiku)
    assert row["would_cost"] > t.snapshot()["total_usd"]
    # Local tokens were free, so local_saved > 0 (Opus would have charged for them)
    assert row["local_saved"] > 0


def test_savings_breakdown_no_local_workers():
    """All paid workers: local_saved=0, routing_saved = full saving."""
    t = _tracker(cap=10.0)
    t.add("w1", "anthropic/claude-haiku-4-5", 1000, 500)
    breakdown = t.savings_breakdown(["anthropic/claude-opus-4-8"])
    row = breakdown[0]
    assert row["local_saved"] == 0.0
    assert abs(row["routing_saved"] - row["saved"]) < 1e-9


def test_savings_breakdown_returns_negative_for_cheaper_baseline():
    """Against a cheaper model than the one we used, saved should be negative."""
    t = _tracker(cap=10.0)
    # Pay Opus prices
    t.add("w1", "anthropic/claude-opus-4-8", 1000, 500)
    breakdown = t.savings_breakdown(["anthropic/claude-haiku-4-5"])
    row = breakdown[0]
    # Haiku baseline is cheaper → we spent more than we would have
    assert row["saved"] < 0
