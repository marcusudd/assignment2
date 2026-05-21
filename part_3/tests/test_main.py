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
