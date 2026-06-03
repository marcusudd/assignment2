"""Tests for Router heuristic and plan parsing."""
import pytest
from unittest.mock import patch, MagicMock
from router import Router, Plan
from config import Config, BackendConfig


def _config() -> Config:
    return Config(
        openrouter_api_key="test",
        locals=[BackendConfig("local-0", "http://localhost:1234/v1", "lm-studio", "qwen3.6")],
        cloud=BackendConfig("cloud", "https://openrouter.ai/api/v1", "test", "anthropic/claude-sonnet-4-6"),
        router_model="anthropic/claude-sonnet-4-6",
        compaction_model="local",
        compaction_token_threshold=8000,
        cost_cap_usd=1.0,
        cost_warning_threshold=0.75,
        max_output=5000,
        max_rounds=10,
        workspace_dir="/tmp/bifrost_ws",
        comparison_models=[],
    )


def _router(cfg=None) -> Router:
    c = cfg or _config()
    return Router(c, c.cloud.base_url, c.cloud.api_key)


def test_simple_task_stays_local():
    r = _router()
    plan = r.plan("List all Python files in the workspace")
    assert plan.mode == 1
    assert len(plan.workers) == 1
    assert plan.workers[0].worker_id == "midgard.primary"
    assert plan.workers[0].backend_name == "local"


def test_search_task_stays_local():
    r = _router()
    plan = r.plan("Find all functions that import requests")
    assert plan.mode == 1


def test_complex_task_not_simple():
    r = _router()
    # Should not be classified as simple (has multi-file feature words)
    with patch("router.call_llm") as mock_llm:
        mock_llm.return_value = (None, 0, 0)  # force fallback
        plan = r.plan("Implement a complete /orders endpoint with inventory and discount logic")
    assert plan.mode == 2  # fallback mode


def test_parse_valid_decomposition():
    r = _router()
    raw = """{
      "mode": 3,
      "reasoning": "Four independent files",
      "workers": [
        {"worker_id": "w1", "role": "coder", "task": "Write model",
         "owned_files": ["models/order.py"], "backend": "local", "rationale": "mechanical"},
        {"worker_id": "w2", "role": "coder", "task": "Write schema",
         "owned_files": ["schemas/order.py"], "backend": "local", "rationale": "mechanical"},
        {"worker_id": "w3", "role": "coder", "task": "Write router",
         "owned_files": ["routers/orders.py"], "backend": "cloud", "rationale": "logic"},
        {"worker_id": "w4", "role": "coder", "task": "Write tests",
         "owned_files": ["tests/test_orders.py"], "backend": "cloud", "rationale": "reasoning"}
      ]
    }"""
    plan = r._parse(raw, "test task")
    assert plan.mode == 3
    assert len(plan.workers) == 4
    assert plan.workers[0].worker_id == "midgard.models-order"
    assert plan.workers[1].worker_id == "midgard.schemas-order"
    assert plan.workers[2].worker_id == "asgard.routers-orders"
    assert plan.workers[3].worker_id == "asgard.tests-test-orders"
    assert plan.workers[0].backend_name == "local"
    assert plan.workers[2].backend_name == "cloud"


def test_parse_overlapping_files_falls_back():
    r = _router()
    raw = """{
      "mode": 3,
      "reasoning": "bad plan",
      "workers": [
        {"worker_id": "w1", "task": "t1", "owned_files": ["same.py"], "backend": "local"},
        {"worker_id": "w2", "task": "t2", "owned_files": ["same.py"], "backend": "cloud"}
      ]
    }"""
    plan = r._parse(raw, "test")
    # Overlapping files → falls back to mode 2
    assert plan.mode == 2


def test_parse_invalid_json_falls_back():
    r = _router()
    plan = r._parse("not json at all !!!", "test")
    assert plan.mode == 2


def test_fast_path_assigns_tests_to_local():
    r = _router()
    task = (
        "Create models/order.py, schemas/order.py, routers/orders.py, "
        "and tests/test_orders.py"
    )
    plan = r._fast_decompose(task)
    assert plan is not None
    assert plan.mode == 3
    by_file = {w.owned_files[0]: w.backend_name for w in plan.workers}
    assert by_file["tests/test_orders.py"] == "local"
    assert by_file["routers/orders.py"] == "cloud"
