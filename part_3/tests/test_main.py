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
    def test_latest_operator_command_finds_last_imperative(self):
        msgs = [
            {"agent_name": "human-operator", "content": "build the first part"},
            {"agent_name": "macmini1", "content": "ok"},
            {"agent_name": "human-operator", "content": "go on"},
            {"agent_name": "human-operator", "content": "create the API next"},
        ]
        assert main.latest_operator_command(msgs) == "create the API next"

    def test_go_on_does_not_replace_build_spec(self):
        msgs = [
            {"agent_name": "human-operator", "content": "Build app.py and models.py", "seq": 1},
            {"agent_name": "macmini1", "content": "ok", "seq": 2},
            {"agent_name": "human-operator", "content": "go on", "seq": 5},
        ]
        assert main.latest_operator_command(msgs) == "Build app.py and models.py"
        assert main.operator_directive_pending(msgs) is True

    def test_latest_operator_command_recognizes_graderbot(self):
        msgs = [{"agent_name": "graderbot", "content": "build something"}]
        assert main.latest_operator_command(msgs) == "build something"

    def test_latest_operator_command_recognizes_grader_bot(self):
        msgs = [{"agent_name": "grader-bot", "content": "implement the API"}]
        assert main.latest_operator_command(msgs) == "implement the API"

    def test_is_operator_agent_normalizes_hyphens(self):
        assert main.is_operator_agent("grader-bot") is True
        assert main.is_operator_agent("human-operator") is True
        assert main.is_operator_agent("macmini1") is False

    def test_is_operator_agent_substring_fallback_matches_variants(self):
        # Unknown live-hub variants should still be recognized via substring search
        assert main.is_operator_agent("Grader-Tom") is True
        assert main.is_operator_agent("exam-judge") is True
        assert main.is_operator_agent("course-operator") is True
        assert main.is_operator_agent("the-examiner") is True
        assert main.is_operator_agent("human-tester") is True

    def test_is_operator_agent_substring_fallback_rejects_normal_agents(self):
        assert main.is_operator_agent("macmini1") is False
        assert main.is_operator_agent("stefan-coder") is False
        assert main.is_operator_agent("summarizer") is False
        assert main.is_operator_agent("sina-factchecker") is False

    def test_has_imperative_no_substring_false_positive(self):
        assert main.has_imperative("we are creative thinkers") is False
        assert main.has_imperative("please create the file") is True

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

    def test_operator_directive_pending_true(self):
        msgs = [{"agent_name": "human-operator", "content": "build a Flask app", "seq": 1}]
        assert main.operator_directive_pending(msgs) is True

    def test_operator_directive_pending_false_for_greeting(self):
        msgs = [{"agent_name": "grader-bot", "content": "welcome everyone", "seq": 1}]
        assert main.operator_directive_pending(msgs) is False

    def test_task_completed_after_success_without_fresh_operator(self):
        msgs = [
            {"agent_name": "human-operator", "content": "build json2csv", "seq": 3},
            {"agent_name": "macmini2", "content": "json2csv.py is fully working", "seq": 10},
        ]
        assert main.task_completed_heuristic(msgs) is True

    def test_task_completed_false_when_operator_after_success(self):
        msgs = [
            {"agent_name": "macmini2", "content": "tool is fully working", "seq": 10},
            {"agent_name": "human-operator", "content": "delete old files and build app", "seq": 15},
        ]
        assert main.task_completed_heuristic(msgs) is False

    def test_task_completed_false_without_peer_success(self):
        msgs = [{"agent_name": "human-operator", "content": "build something", "seq": 1}]
        assert main.task_completed_heuristic(msgs) is False


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
class TestEmptyPromise:
    """is_empty_promise — catches 'I will...' without actual delivery."""

    def test_pure_promise_caught(self):
        assert main.is_empty_promise("I will start by building the backend") is True
        assert main.is_empty_promise("I'll begin with FastAPI") is True
        assert main.is_empty_promise("I plan to add tests next") is True
        assert main.is_empty_promise("Next, I'll set up the database") is True
        assert main.is_empty_promise("I'm going to handle the frontend") is True

    def test_pure_delivery_not_caught(self):
        assert main.is_empty_promise("Created app.py — runs cleanly.") is False
        assert main.is_empty_promise("Edited db.py to add new schema.") is False
        assert main.is_empty_promise("Verified the API responds with 200.") is False

    def test_pass_not_caught(self):
        assert main.is_empty_promise("PASS") is False

    def test_empty_string_not_caught(self):
        assert main.is_empty_promise("") is False

    def test_no_future_tense_not_caught(self):
        assert main.is_empty_promise("The workspace is empty.") is False


class TestNonDeliveryReply:
    def test_complaint_without_delivery_blocked(self):
        assert main.is_non_delivery_reply(
            "I am still facing the same issue with creating the README.md file."
        ) is True

    def test_delivery_not_blocked(self):
        assert main.is_non_delivery_reply("Created app.py — runs cleanly.") is False

    def test_autosummary_not_blocked(self):
        assert main.is_non_delivery_reply("[auto-summary] ran `ls`") is False

    def test_hub_reply_blocked_combines_checks(self):
        assert main.hub_reply_blocked("I will build it") is True
        assert main.hub_reply_blocked("facing repeated errors") is True


class TestDisallowedPromise:
    """has_disallowed_promise — blocks mixed delivery + future-tense in one message."""

    def test_mixed_promise_blocked(self):
        assert main.has_disallowed_promise(
            "Created `requirements.txt`. Next, I will create `models.py`."
        ) is True
        assert main.has_disallowed_promise(
            "Created app.py with /healthz. I'll add models.py next."
        ) is True

    def test_pure_delivery_allowed(self):
        assert main.has_disallowed_promise("Created app.py — runs cleanly.") is False

    def test_autosummary_not_blocked(self):
        assert main.has_disallowed_promise("[auto-summary] ran `ls`") is False


class TestWorkspaceGap:
    def test_extract_filenames_from_operator_text(self):
        text = "Need app.py, models.py, and project_cli.py with verify.sh"
        names = main.extract_required_filenames(text)
        assert "app.py" in names
        assert "models.py" in names
        assert "project_cli.py" in names

    def test_gap_section_lists_missing(self, tmp_path):
        (tmp_path / "models.py").write_text("# m\n")
        op = "Build app.py, models.py, db.py for the API"
        section = main.build_workspace_gap_section(op, str(tmp_path))
        assert "WORKSPACE GAP" in section
        assert "app.py" in section
        assert "db.py" in section
        assert "models.py" not in section or "Already on disk" in section


class TestDelegation:
    def test_delegated_when_mentioned_with_please(self):
        name = main.AGENT_NAME
        msgs = [
            {"agent_name": "macmini2", "content": f"@{name} please take the next file"},
        ]
        assert main.was_delegated_to_me(msgs) is True

    def test_not_delegated_without_hint(self):
        name = main.AGENT_NAME
        msgs = [{"agent_name": "macmini2", "content": f"Great work @{name}"}]
        assert main.was_delegated_to_me(msgs) is False


class TestSuppressAutosum:
    """Anti-loop for [auto-summary] fallbacks within 60s."""

    def test_first_autosum_not_suppressed(self):
        # No prior autosum → always send
        assert main.should_suppress_autosum(
            "[auto-summary] Actions this turn: ran `ls`",
            last_text="", age_seconds=0,
        ) is False

    def test_identical_autosum_within_60s_suppressed(self):
        text = "[auto-summary] Actions this turn: ran `ls`; ran `find`"
        assert main.should_suppress_autosum(text, last_text=text, age_seconds=10) is True

    def test_near_identical_autosum_suppressed(self):
        a = "[auto-summary] Actions this turn: ran `ls -la`; ran `find . -type f`"
        b = "[auto-summary] Actions this turn: ran `ls -la`; ran `find . -name x`"
        assert main.should_suppress_autosum(a, last_text=b, age_seconds=15) is True

    def test_autosum_after_60s_not_suppressed(self):
        text = "[auto-summary] Actions this turn: ran `ls`"
        assert main.should_suppress_autosum(text, last_text=text, age_seconds=61) is False

    def test_non_autosum_not_suppressed(self):
        # Real prose reports always go through
        assert main.should_suppress_autosum(
            "Built app.py — runs cleanly. @macmini2 please add tests.",
            last_text="some prior text", age_seconds=5,
        ) is False

    def test_different_autosum_content_not_suppressed(self):
        # Two genuinely different summaries should both be sent
        a = "[auto-summary] Actions this turn: edited `app.py`; ran `python app.py`"
        b = "[auto-summary] Actions this turn: read `db.py`; edited `db.py`"
        assert main.should_suppress_autosum(a, last_text=b, age_seconds=10) is False


class TestCallLLMExceptionHandling:
    def test_connection_error_returns_none(self):
        # Any non-APIError exception (network/TLS/JSON decode) must not propagate
        with patch("agent.OpenAI") as mock_openai_class:
            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = ConnectionError("dns fail")
            mock_openai_class.return_value = mock_client
            result = agent._call_llm([{"role": "user", "content": "hi"}], "sys")
            assert result is None

    def test_value_error_returns_none(self):
        with patch("agent.OpenAI") as mock_openai_class:
            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = ValueError("bad JSON")
            mock_openai_class.return_value = mock_client
            result = agent._call_llm([{"role": "user", "content": "hi"}], "sys")
            assert result is None


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


class TestProtectedFiles:
    """rm / find -delete should be blocked for files in the active operator spec."""

    def teardown_method(self):
        # Always clear the module-level set so tests don't bleed into each other
        agent.set_protected_files([])

    def test_no_protection_when_set_empty(self):
        agent.set_protected_files([])
        assert agent.security_check("rm app.py") is None

    def test_blocks_rm_of_protected_file_no_flags(self):
        agent.set_protected_files(["app.py", "models.py"])
        reason = agent.security_check("rm app.py")
        assert reason is not None
        assert "app.py" in reason

    def test_blocks_rm_of_protected_file_with_path(self):
        agent.set_protected_files(["app.py"])
        assert agent.security_check("rm ./app.py") is not None

    def test_allows_rm_of_unprotected_file(self):
        agent.set_protected_files(["models.py"])
        assert agent.security_check("rm test.txt") is None

    def test_blocks_find_delete_when_protected(self):
        agent.set_protected_files(["app.py"])
        assert agent.security_check("find . -type f -delete") is not None
        assert agent.security_check("find . -name '*.py' -delete") is not None

    def test_allows_find_delete_when_no_protection(self):
        agent.set_protected_files([])
        assert agent.security_check("find . -type f -delete") is None

    def test_gitkeep_never_protected(self):
        # set_protected_files filters .gitkeep out
        agent.set_protected_files(["app.py", ".gitkeep"])
        assert agent.security_check("rm .gitkeep") is None

    def test_substring_match_does_not_overprotect(self):
        # "appendix.py" is NOT protected just because "app.py" is
        agent.set_protected_files(["app.py"])
        assert agent.security_check("rm appendix.py") is None


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

    def test_read_file_blocks_env(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("SECRET=1")
        with patch.object(agent, "WORKSPACE_DIR", str(tmp_path)):
            result = agent.tool_read_file(".env")
        assert "not allowed" in result


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
