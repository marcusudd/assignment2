"""Tests for context compaction (VG.2)."""
import pytest
from unittest.mock import patch, MagicMock
from compactor import compact_if_needed, _estimate_tokens
from config import Config, BackendConfig


def _config(threshold=100) -> Config:
    return Config(
        openrouter_api_key="test",
        local=BackendConfig("http://localhost:1234/v1", "lm-studio", "qwen"),
        cloud=BackendConfig("https://openrouter.ai/api/v1", "test", "claude-sonnet"),
        router_model="claude-sonnet",
        compaction_model="cloud",
        compaction_token_threshold=threshold,
        cost_cap_usd=1.0,
        cost_warning_threshold=0.75,
        max_output=5000,
        max_rounds=10,
        workspace_dir="/tmp/ws",
        comparison_models=[],
    )


def _big_history(n=20) -> list[dict]:
    return [
        {"role": "user" if i % 2 == 0 else "assistant",
         "content": f"Turn {i}: " + "x" * 80}
        for i in range(n)
    ]


def test_no_compact_below_threshold():
    history = _big_history(3)
    result = compact_if_needed(history, _config(threshold=10000), "url", "key")
    assert result is False
    assert len(history) == 3


def test_compact_above_threshold():
    history = _big_history(20)
    original_len = len(history)
    cfg = _config(threshold=10)  # very low — guaranteed to trigger

    mock_response = MagicMock()
    mock_response.choices[0].message.content = "Summary of earlier turns."

    with patch("compactor.call_llm", return_value=(mock_response, 100, 50)):
        result = compact_if_needed(history, cfg, "url", "key")

    assert result is True
    assert len(history) < original_len
    # Must keep at least the tail (4 turns) + 1 summary
    assert len(history) <= 5
    assert history[0]["role"] == "system"
    assert "Compacted" in history[0]["content"] or "Summary" in history[0]["content"]


def test_compact_failed_llm_keeps_history():
    history = _big_history(20)
    cfg = _config(threshold=10)

    with patch("compactor.call_llm", return_value=(None, 0, 0)):
        result = compact_if_needed(history, cfg, "url", "key")

    assert result is False
    assert len(history) == 20


def test_estimate_tokens():
    history = [{"role": "user", "content": "x" * 400}]
    est = _estimate_tokens(history)
    assert est == 100  # 400 chars / 4
