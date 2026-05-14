"""
Integration tests — make real Anthropic API calls.

Default run (pytest tests/) skips these.
Run explicitly with: pytest tests/ -m integration -v
"""

import os
import pytest
import main
from main import call_llm, parse_action, parse_answer, parse_thought, run_agent

pytestmark = pytest.mark.integration

SYSTEM = (
    "You are a ReAct agent. Use the bash tool to run shell commands.\n\n"
    "Always respond in one of these two formats:\n\n"
    "Format 1 — when you need to run a command:\n"
    "<thought>your reasoning</thought>\n"
    "<action><tool>bash</tool><input>shell command</input></action>\n\n"
    "Format 2 — when you have a final answer:\n"
    "<thought>your reasoning</thought>\n"
    "<answer>your answer here</answer>\n\n"
    "CRITICAL: STOP immediately after </action>. "
    "Never write Observation or guess what the command will output. "
    "Never include <answer> in the same response as <action>."
)


@pytest.fixture(autouse=True, scope="module")
def require_api_key():
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")


# ============================================================
# call_llm — stop_sequence and format
# ============================================================

class TestCallLLMIntegration:
    def test_action_produces_action_stop(self):
        messages = [{"role": "user", "content": "Run `ls /tmp` using bash."}]
        text, reason = call_llm(messages, SYSTEM)
        assert reason == "action_stop", f"got {reason!r} — text: {text!r}"

    def test_action_stop_has_no_closing_tag(self):
        messages = [{"role": "user", "content": "Run `ls /tmp` using bash."}]
        text, reason = call_llm(messages, SYSTEM)
        assert reason == "action_stop"
        assert "</action>" not in text, "stop_sequence should have cut off before </action>"

    def test_action_stop_text_is_parseable_after_restore(self):
        messages = [{"role": "user", "content": "Run `ls /tmp` using bash."}]
        text, reason = call_llm(messages, SYSTEM)
        assert reason == "action_stop"
        action = parse_action(text + "</action>")
        assert action is not None, "parse_action failed after restoring </action>"
        assert action["tool"] == "bash"
        assert len(action["input"]) > 0

    def test_action_response_contains_thought(self):
        messages = [{"role": "user", "content": "Run `echo hello` using bash."}]
        text, reason = call_llm(messages, SYSTEM)
        full = text + ("</action>" if reason == "action_stop" else "")
        assert parse_thought(full) is not None, "model should include <thought> before action"

    def test_direct_answer_produces_end_turn(self):
        messages = [{"role": "user", "content": "What is the capital of Sweden? Use <answer> tags."}]
        text, reason = call_llm(messages, SYSTEM)
        assert reason == "end_turn", f"got {reason!r} — text: {text!r}"

    def test_direct_answer_is_parseable(self):
        messages = [{"role": "user", "content": "What is the capital of Sweden? Use <answer> tags."}]
        text, reason = call_llm(messages, SYSTEM)
        assert reason == "end_turn"
        answer = parse_answer(text)
        assert answer is not None, "parse_answer returned None — model may not have used <answer> tags"
        assert len(answer) > 0


# ============================================================
# run_agent — full loop with mocked execute_command
# ============================================================

class TestRunAgentIntegration:
    def test_direct_answer_returns_string(self, monkeypatch):
        monkeypatch.setattr(main, "execute_command", lambda cmd: "mocked")
        result = run_agent(
            "What is the capital of Sweden? Answer directly using <answer> tags, no bash needed.",
            [],
            SYSTEM,
        )
        assert isinstance(result, str) and len(result) > 0

    def test_direct_answer_content_is_correct(self, monkeypatch):
        monkeypatch.setattr(main, "execute_command", lambda cmd: "mocked")
        result = run_agent(
            "What is the capital of Sweden? Answer directly using <answer> tags, no bash needed.",
            [],
            SYSTEM,
        )
        assert "Stockholm" in result, f"expected Stockholm in answer, got: {result!r}"

    def test_action_observation_loop_completes(self, monkeypatch):
        monkeypatch.setattr(main, "execute_command", lambda cmd: "hello.txt\nworld.txt")
        result = run_agent(
            "Run `ls` to list workspace files, then summarize what you found.",
            [],
            SYSTEM,
        )
        assert isinstance(result, str) and len(result) > 0

    def test_history_ends_with_assistant_after_success(self, monkeypatch):
        monkeypatch.setattr(main, "execute_command", lambda cmd: "mocked")
        history = []
        run_agent(
            "What is 2+2? Answer directly using <answer> tags.",
            history,
            SYSTEM,
        )
        assert len(history) >= 2
        assert history[0] == {"role": "user", "content": "What is 2+2? Answer directly using <answer> tags."}
        assert history[-1]["role"] == "assistant"

    def test_second_question_after_success_works(self, monkeypatch):
        monkeypatch.setattr(main, "execute_command", lambda cmd: "mocked")
        history = []
        run_agent("What is 2+2? Use <answer> tags.", history, SYSTEM)
        result = run_agent("And what is 3+3? Use <answer> tags.", history, SYSTEM)
        assert isinstance(result, str) and len(result) > 0
        assert history[-1]["role"] == "assistant"
