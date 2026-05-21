"""
Unit tests for Part 3 — no API calls, no hub connection.
"""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
import agent
import hub
import main
from console import AgentState, Console
from agent import TokenCounter


# ---------------------------------------------------------------------------
# TokenCounter
# ---------------------------------------------------------------------------
class TestTokenCounter:
    def test_starts_at_zero(self):
        tc = TokenCounter(cap=1000)
        assert tc.total == 0

    def test_not_exceeded_below_cap(self):
        tc = TokenCounter(cap=1000)
        tc.add(500)
        assert not tc.exceeded()

    def test_exceeded_at_cap(self):
        tc = TokenCounter(cap=1000)
        tc.add(1000)
        assert tc.exceeded()

    def test_exceeded_above_cap(self):
        tc = TokenCounter(cap=100)
        tc.add(200)
        assert tc.exceeded()

    def test_cap_changeable(self):
        tc = TokenCounter(cap=100)
        tc.add(150)
        assert tc.exceeded()
        tc.cap = 200
        assert not tc.exceeded()

    def test_soft_exceeded_below_threshold(self):
        tc = TokenCounter(cap=1000)
        tc.add(749)
        assert not tc.soft_exceeded()

    def test_soft_exceeded_at_threshold(self):
        tc = TokenCounter(cap=1000)
        tc.add(750)
        assert tc.soft_exceeded()

    def test_soft_exceeded_above_threshold(self):
        tc = TokenCounter(cap=1000)
        tc.add(800)
        assert tc.soft_exceeded()
        assert not tc.hard_exceeded()

    def test_hard_exceeded_below_threshold(self):
        tc = TokenCounter(cap=1000)
        tc.add(899)
        assert not tc.hard_exceeded()

    def test_hard_exceeded_at_threshold(self):
        tc = TokenCounter(cap=1000)
        tc.add(900)
        assert tc.hard_exceeded()

    def test_tier_ordering(self):
        tc = TokenCounter(cap=1000)
        tc.add(600)
        assert not tc.soft_exceeded()
        assert not tc.hard_exceeded()
        assert not tc.exceeded()
        tc.add(200)  # now at 800
        assert tc.soft_exceeded()
        assert not tc.hard_exceeded()
        tc.add(100)  # now at 900
        assert tc.soft_exceeded()
        assert tc.hard_exceeded()
        assert not tc.exceeded()
        tc.add(100)  # now at 1000
        assert tc.exceeded()


# ---------------------------------------------------------------------------
# AgentState
# ---------------------------------------------------------------------------
class TestAgentState:
    def test_initial_state(self):
        tc = TokenCounter(cap=1000)
        s = AgentState(msg_cap=10, token_counter=tc)
        assert s.messages_sent == 0
        assert s.msg_cap == 10
        assert s.paused is False
        assert s.running is True
        assert s.last_seen == 0

    def test_msg_cap_adjustable(self):
        tc = TokenCounter(cap=1000)
        s = AgentState(msg_cap=5, token_counter=tc)
        s.msg_cap = 20
        assert s.msg_cap == 20


# ---------------------------------------------------------------------------
# looks_duplicate — anti-duplication final-check
# ---------------------------------------------------------------------------
class TestLooksDuplicate:
    def test_same_file_same_action_is_duplicate(self):
        reply = "I created `app.py` with a Flask route."
        others = [{"agent_name": "other", "content": "I created `app.py` for the API."}]
        assert main.looks_duplicate(reply, others) is True

    def test_same_file_different_actions_still_duplicate(self):
        reply = "I created `models.py`."
        others = [{"agent_name": "other", "content": "I verified `models.py` works."}]
        assert main.looks_duplicate(reply, others) is True

    def test_different_files_not_duplicate(self):
        reply = "I created `auth.py` with login logic."
        others = [{"agent_name": "other", "content": "I created `routes.py`."}]
        assert main.looks_duplicate(reply, others) is False

    def test_no_file_in_reply_not_duplicate(self):
        reply = "Hi, what should we build?"
        others = [{"agent_name": "other", "content": "I created `app.py`."}]
        assert main.looks_duplicate(reply, others) is False

    def test_no_action_in_reply_not_duplicate(self):
        reply = "The file `app.py` looks interesting."
        others = [{"agent_name": "other", "content": "I created `app.py`."}]
        assert main.looks_duplicate(reply, others) is False

    def test_empty_others_not_duplicate(self):
        assert main.looks_duplicate("I created `app.py`", []) is False

    def test_identical_text_is_duplicate(self):
        reply = "Hi — what should we build?"
        others = [{"agent_name": "other", "content": "Hi — what should we build?"}]
        assert main.looks_duplicate(reply, others) is True

    def test_near_identical_verifications_are_duplicate(self):
        reply = "I examined the file structure and found the following files in todo_api: app.py, requirements.txt"
        others = [{"agent_name": "other", "content": "I checked the file structure and found the following files in todo_api: app.py, requirements.txt"}]
        assert main.looks_duplicate(reply, others) is True

    def test_very_short_messages_not_duplicate(self):
        # Avoid false positives on short greetings like "ok" "hi"
        reply = "ok"
        others = [{"agent_name": "other", "content": "ok"}]
        assert main.looks_duplicate(reply, others) is False

    def test_different_text_not_duplicate(self):
        reply = "I'll handle the database schema design"
        others = [{"agent_name": "other", "content": "Working on the frontend templates now"}]
        assert main.looks_duplicate(reply, others) is False


# ---------------------------------------------------------------------------
# Operator command detection
# ---------------------------------------------------------------------------
class TestOperatorDetection:
    def test_latest_operator_command_finds_last(self):
        msgs = [
            {"agent_name": "human-operator", "content": "first command"},
            {"agent_name": "macmini1", "content": "ok"},
            {"agent_name": "human-operator", "content": "second command"},
        ]
        assert main.latest_operator_command(msgs) == "second command"

    def test_latest_operator_command_recognizes_graderbot(self):
        msgs = [{"agent_name": "graderbot", "content": "build something"}]
        assert main.latest_operator_command(msgs) == "build something"

    def test_latest_operator_command_none_when_only_agents(self):
        msgs = [{"agent_name": "macmini1", "content": "hello"}]
        assert main.latest_operator_command(msgs) is None

    def test_has_imperative_detects_build(self):
        assert main.has_imperative("Please build a Flask app") is True

    def test_has_imperative_detects_delete(self):
        assert main.has_imperative("Delete the old stuff") is True

    def test_has_imperative_false_for_greeting(self):
        assert main.has_imperative("hello everyone") is False

    def test_has_imperative_false_for_none(self):
        assert main.has_imperative(None) is False


# ---------------------------------------------------------------------------
# Console commands
# ---------------------------------------------------------------------------
class TestConsole:
    def _make(self, msg_cap=10, token_cap=1000):
        tc = TokenCounter(cap=token_cap)
        state = AgentState(msg_cap=msg_cap, token_counter=tc)
        console = Console(state)
        return console, state

    def test_pause(self):
        console, state = self._make()
        console._handle("pause")
        assert state.paused is True

    def test_resume(self):
        console, state = self._make()
        state.paused = True
        console._handle("resume")
        assert state.paused is False

    def test_quit(self):
        console, state = self._make()
        console._handle("quit")
        assert state.running is False

    def test_cap_command(self):
        console, state = self._make(token_cap=1000)
        console._handle("cap 9999")
        assert state.token_counter.cap == 9999

    def test_limit_command(self):
        console, state = self._make(msg_cap=10)
        console._handle("limit 3")
        assert state.msg_cap == 3

    def test_invalid_cap(self, capsys):
        console, state = self._make()
        console._handle("cap notanumber")
        assert state.token_counter.cap == 1000  # unchanged


# ---------------------------------------------------------------------------
# hub — dry-run mode
# ---------------------------------------------------------------------------
class TestHubDryRun:
    def test_send_returns_minus_one_in_dry_run(self, capsys):
        with patch.object(hub, "DRY_RUN", True):
            result = hub.send_message("test-agent", "hello")
        assert result == -1

    def test_send_prints_in_dry_run(self, capsys):
        with patch.object(hub, "DRY_RUN", True):
            hub.send_message("test-agent", "hello world")
        out = capsys.readouterr().out
        assert "test-agent" in out
        assert "hello world" in out


# ---------------------------------------------------------------------------
# hub — fetch_messages
# ---------------------------------------------------------------------------
class TestHubFetch:
    def test_returns_messages_list(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"messages": [{"seq": 1, "agent_name": "a", "content": "hi"}]}
        mock_resp.raise_for_status.return_value = None

        with patch("hub.requests.get", return_value=mock_resp), \
             patch.object(hub, "_last_request_time", 0):
            msgs = hub.fetch_messages(0)
        assert len(msgs) == 1
        assert msgs[0]["seq"] == 1

    def test_returns_empty_on_no_messages(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status.return_value = None

        with patch("hub.requests.get", return_value=mock_resp), \
             patch.object(hub, "_last_request_time", 0):
            msgs = hub.fetch_messages(5)
        assert msgs == []


# ---------------------------------------------------------------------------
# hub — send_message LIVE (mocked HTTP)
# ---------------------------------------------------------------------------
class TestHubSend:
    def test_send_posts_correct_payload(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "ok", "seq": 7}
        mock_resp.raise_for_status.return_value = None

        with patch("hub.requests.post", return_value=mock_resp) as mock_post, \
             patch.object(hub, "DRY_RUN", False), \
             patch.object(hub, "_last_request_time", 0):
            seq = hub.send_message("marcus-developer", "Hello!")

        assert seq == 7
        payload = mock_post.call_args.kwargs["json"]
        assert payload["agent_name"] == "marcus-developer"
        assert payload["content"] == "Hello!"

    def test_raises_rate_limit_on_429(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.text = "rate limited"

        with patch("hub.requests.post", return_value=mock_resp), \
             patch.object(hub, "DRY_RUN", False), \
             patch.object(hub, "_last_request_time", 0):
            with pytest.raises(hub.RateLimitError):
                hub.send_message("marcus-developer", "Hello!")


# ---------------------------------------------------------------------------
# Hub retry logic
# ---------------------------------------------------------------------------
class TestHubRetry:
    def test_retryable_5xx(self):
        assert hub._retryable(500, None) is True
        assert hub._retryable(502, None) is True
        assert hub._retryable(503, None) is True

    def test_not_retryable_4xx(self):
        assert hub._retryable(400, None) is False
        assert hub._retryable(401, None) is False
        assert hub._retryable(404, None) is False
        assert hub._retryable(429, None) is False

    def test_not_retryable_2xx(self):
        assert hub._retryable(200, None) is False

    def test_retryable_timeout(self):
        import requests as rq
        assert hub._retryable(None, rq.Timeout()) is True
        assert hub._retryable(None, rq.ConnectionError()) is True

    def test_not_retryable_value_error(self):
        assert hub._retryable(None, ValueError("boom")) is False

    def test_not_retryable_non_int_status(self):
        # Defensive: MagicMock-style status_code → no retry
        assert hub._retryable("not an int", None) is False
        assert hub._retryable(None, None) is False


# ---------------------------------------------------------------------------
# security_check (copied from Part 2 into agent.py)
# ---------------------------------------------------------------------------
class TestSecurityCheck:
    def test_allows_ls(self):
        assert agent.security_check("ls -la") is None

    def test_blocks_chaining(self):
        assert agent.security_check("pwd && ls") is not None

    def test_blocks_env(self):
        assert agent.security_check("env") is not None

    def test_blocks_rm_rf(self):
        assert agent.security_check("rm -rf /") is not None

    def test_blocks_tilde(self):
        assert agent.security_check("ls ~") is not None

    def test_blocks_secret_var(self):
        assert agent.security_check("echo $OPENROUTER_API_KEY") is not None


# ---------------------------------------------------------------------------
# resolve_path
# ---------------------------------------------------------------------------
class TestResolvePath:
    def test_simple_file(self, tmp_path):
        with patch.object(agent, "WORKSPACE_DIR", str(tmp_path)):
            result = agent.resolve_path("foo.txt")
        assert result == (tmp_path / "foo.txt").resolve()

    def test_traversal_blocked(self, tmp_path):
        with patch.object(agent, "WORKSPACE_DIR", str(tmp_path)):
            result = agent.resolve_path("../../etc/passwd")
        assert result is None


# ---------------------------------------------------------------------------
# decide — self-echo guard
# ---------------------------------------------------------------------------
class TestDecideSelfEcho:
    def test_pass_when_last_3_from_self(self):
        msgs = [
            {"seq": 1, "agent_name": "marcus-developer", "content": "a"},
            {"seq": 2, "agent_name": "marcus-developer", "content": "b"},
            {"seq": 3, "agent_name": "marcus-developer", "content": "c"},
        ]
        tc = TokenCounter(cap=100000)
        result = agent.decide(msgs, "marcus-developer", "sys", [], tc)
        assert result == "PASS"

    def test_responds_when_others_posted(self):
        msgs = [
            {"seq": 1, "agent_name": "alice", "content": "Hello!"},
        ]
        tc = TokenCounter(cap=100000)

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(
            message=MagicMock(content="Hi Alice!", tool_calls=None),
            finish_reason="stop",
        )]
        mock_resp.usage = MagicMock(total_tokens=50)

        with patch("agent.OpenAI") as MockOpenAI:
            MockOpenAI.return_value.chat.completions.create.return_value = mock_resp
            result = agent.decide(msgs, "marcus-developer", "sys", [], tc)

        assert result == "Hi Alice!"
        assert tc.total == 50
