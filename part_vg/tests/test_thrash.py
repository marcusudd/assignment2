"""Tests for thrash-detection: 3 consecutive tool failures escalate local→cloud."""
from unittest.mock import MagicMock, patch
from backends import BackendSpec
from config import Config, BackendConfig
from cost import CostTracker
from state import StateRegistry
from subagent import (
    SubAgent,
    WorkerPlan,
    _BASE_MAX_TOKENS,
    _HIGH_MAX_TOKENS,
    _MAX_MAX_TOKENS,
)


def _local_spec() -> BackendSpec:
    return BackendSpec("local-0", "http://localhost:1234/v1", "lm-studio", "gemma", is_local=True)


def _cloud_spec() -> BackendSpec:
    return BackendSpec("cloud", "https://openrouter.ai/api/v1", "key", "anthropic/claude-haiku-4-5", is_local=False)


def _config() -> Config:
    return Config(
        openrouter_api_key="test",
        locals=[BackendConfig("local-0", "http://localhost:1234/v1", "lm-studio", "gemma")],
        cloud=BackendConfig("cloud", "https://openrouter.ai/api/v1", "key", "haiku"),
        router_model="haiku",
        compaction_model="cloud",
        compaction_token_threshold=8000,
        cost_cap_usd=10.0,
        cost_warning_threshold=0.75,
        max_output=5000,
        max_rounds=20,
        workspace_dir="/tmp/ws",
        comparison_models=[],
    )


def _make_agent() -> SubAgent:
    plan = WorkerPlan(
        worker_id="midgard.test",
        role="coder",
        task="implement something",
        owned_files=["test.py"],
        backend_name="local",
        local_tier="standard",
    )
    return SubAgent(
        plan=plan,
        active_backend=_local_spec(),
        cloud_backend=_cloud_spec(),
        cost_tracker=CostTracker(cap_usd=10.0, prices_path="model_prices.json"),
        registry=StateRegistry(),
        config=_config(),
        system_prompt="You are a coder.",
    )


def _make_response(tool_name: str = "edit_file", tool_args: str = '{"path":"x.py","content":""}') -> MagicMock:
    tc = MagicMock()
    tc.id = "tc1"
    tc.function.name = tool_name
    tc.function.arguments = tool_args
    msg = MagicMock()
    msg.content = None
    msg.tool_calls = [tc]
    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = "tool_calls"
    response = MagicMock()
    response.choices = [choice]
    return response


def test_initial_max_tokens_test_file_coder():
    agent = _make_agent()
    assert agent._initial_max_tokens() == _HIGH_MAX_TOKENS


def test_initial_max_tokens_non_test_coder():
    plan = WorkerPlan(
        worker_id="midgard.models-order",
        role="coder",
        task="implement models",
        owned_files=["models/order.py"],
        backend_name="local",
    )
    agent = SubAgent(
        plan=plan,
        active_backend=_local_spec(),
        cloud_backend=_cloud_spec(),
        cost_tracker=CostTracker(cap_usd=10.0, prices_path="model_prices.json"),
        registry=StateRegistry(),
        config=_config(),
        system_prompt="You are a coder.",
    )
    assert agent._initial_max_tokens() == _BASE_MAX_TOKENS


def test_initial_max_tokens_integrator():
    plan = WorkerPlan(
        worker_id="asgard.integration",
        role="integrator",
        task="integrate",
        owned_files=[],
        backend_name="cloud",
    )
    agent = SubAgent(
        plan=plan,
        active_backend=_cloud_spec(),
        cloud_backend=_cloud_spec(),
        cost_tracker=CostTracker(cap_usd=10.0, prices_path="model_prices.json"),
        registry=StateRegistry(),
        config=_config(),
        system_prompt="You are an integrator.",
    )
    assert agent._initial_max_tokens() == _HIGH_MAX_TOKENS


def test_length_truncation_retries_with_higher_max_tokens():
    agent = _make_cloud_agent()
    max_tokens_seen = []

    def fake_llm(*args, **kwargs):
        max_tokens_seen.append(kwargs.get("max_tokens"))
        if len(max_tokens_seen) == 1:
            msg = MagicMock()
            msg.content = None
            msg.tool_calls = [MagicMock()]
            msg.tool_calls[0].id = "tc1"
            msg.tool_calls[0].function.name = "bash"
            msg.tool_calls[0].function.arguments = '{"command": "echo ok"}'
            choice = MagicMock()
            choice.message = msg
            choice.finish_reason = "length"
            response = MagicMock()
            response.choices = [choice]
            return response, 10, 5
        success = MagicMock()
        success_msg = MagicMock()
        success_msg.content = "Done."
        success_msg.tool_calls = None
        success_choice = MagicMock()
        success_choice.message = success_msg
        success_choice.finish_reason = "stop"
        success.choices = [success_choice]
        return success, 5, 3

    with patch("subagent.call_llm", side_effect=fake_llm), \
         patch("subagent.dispatch_tool", return_value="(no output)"), \
         patch("subagent.compact_if_needed", return_value=False):
        result = agent._loop()

    assert result == "Done."
    assert max_tokens_seen[0] == _HIGH_MAX_TOKENS
    assert max_tokens_seen[1] == min(_HIGH_MAX_TOKENS + 4096, _MAX_MAX_TOKENS)
    assert len(agent.history) == 1


def test_three_consecutive_failures_trigger_escalation():
    agent = _make_agent()
    assert agent._active.is_local is True

    error_result = "ERROR: old_str not found — use read_file to verify exact content."
    success_response = MagicMock()
    success_msg = MagicMock()
    success_msg.content = "All done."
    success_msg.tool_calls = None
    success_choice = MagicMock()
    success_choice.message = success_msg
    success_choice.finish_reason = "stop"
    success_response.choices = [success_choice]

    call_count = [0]

    def fake_llm(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] <= 3:
            return _make_response(), 10, 5
        return success_response, 5, 3

    with patch("subagent.call_llm", side_effect=fake_llm), \
         patch("subagent.dispatch_tool", return_value=error_result), \
         patch("subagent.compact_if_needed", return_value=False):
        agent._loop()

    # After 3 failures the agent should have escalated to cloud
    assert agent._escalated is True
    assert agent._active.is_local is False


def test_success_resets_failure_counter():
    agent = _make_agent()

    results = ["ERROR: something", "ERROR: something", "OK: success"]
    result_iter = iter(results)

    success_response = MagicMock()
    success_msg = MagicMock()
    success_msg.content = "Done."
    success_msg.tool_calls = None
    success_choice = MagicMock()
    success_choice.message = success_msg
    success_choice.finish_reason = "stop"
    success_response.choices = [success_choice]

    call_count = [0]

    def fake_llm(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] <= 3:
            return _make_response(), 10, 5
        return success_response, 5, 3

    def fake_dispatch(name, inputs, workspace_dir, **kwargs):
        return next(result_iter, "OK: done")

    with patch("subagent.call_llm", side_effect=fake_llm), \
         patch("subagent.dispatch_tool", side_effect=fake_dispatch), \
         patch("subagent.compact_if_needed", return_value=False):
        agent._loop()

    # 2 errors then a success → counter reset → no escalation from thrash
    assert agent._escalated is False
    assert agent._consecutive_tool_failures == 0


def _make_cloud_agent() -> SubAgent:
    plan = WorkerPlan(
        worker_id="asgard.tests",
        role="coder",
        task="write tests",
        owned_files=["tests/test_x.py"],
        backend_name="cloud",
        local_tier="standard",
    )
    return SubAgent(
        plan=plan,
        active_backend=_cloud_spec(),
        cloud_backend=_cloud_spec(),
        cost_tracker=CostTracker(cap_usd=10.0, prices_path="model_prices.json"),
        registry=StateRegistry(),
        config=_config(),
        system_prompt="You are a coder.",
    )


def test_cloud_circuit_breaker_aborts_after_five_failures():
    agent = _make_cloud_agent()
    assert agent._active.is_local is False

    error_result = "ERROR: invalid tool argument JSON from model"
    call_count = [0]

    def fake_llm(*args, **kwargs):
        call_count[0] += 1
        return _make_response(tool_name="bash", tool_args="{}"), 10, 5

    with patch("subagent.call_llm", side_effect=fake_llm), \
         patch("subagent.dispatch_tool", return_value=error_result), \
         patch("subagent.compact_if_needed", return_value=False):
        result = agent._loop()

    assert "Aborted: repeated tool failures on cloud worker" in result
    assert call_count[0] <= 6
