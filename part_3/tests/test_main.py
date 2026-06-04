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

    def test_task_completed_false_when_required_file_missing(self, tmp_path):
        # 3 files required (tasks.json, todo.py, README.md), only 2 exist on disk
        (tmp_path / "tasks.json").write_text("[]")
        (tmp_path / "todo.py").write_text("# cli")
        msgs = [
            {"agent_name": "human-operator", "content":
             "build tasks.json, todo.py, README.md", "seq": 3},
            {"agent_name": "macmini2", "content": "todo.py is working correctly", "seq": 10},
        ]
        # Without workspace check → True (peer reported success)
        assert main.task_completed_heuristic(msgs) is True
        # With workspace check → False (README.md missing)
        assert main.task_completed_heuristic(
            msgs,
            op_cmd="build tasks.json, todo.py, README.md",
            workspace_dir=str(tmp_path),
        ) is False

    def test_task_completed_true_when_all_required_present(self, tmp_path):
        (tmp_path / "tasks.json").write_text("[]")
        (tmp_path / "todo.py").write_text("# cli")
        (tmp_path / "README.md").write_text("# usage")
        msgs = [
            {"agent_name": "human-operator", "content":
             "build tasks.json, todo.py, README.md", "seq": 3},
            {"agent_name": "macmini2", "content": "todo.py is working correctly", "seq": 10},
        ]
        assert main.task_completed_heuristic(
            msgs,
            op_cmd="build tasks.json, todo.py, README.md",
            workspace_dir=str(tmp_path),
        ) is True

    def test_task_completed_workspace_check_skipped_for_single_file(self, tmp_path):
        # Single-file task — workspace check only kicks in for multi-file (>=2)
        msgs = [
            {"agent_name": "human-operator", "content": "build hello.py", "seq": 3},
            {"agent_name": "macmini2", "content": "hello.py is working", "seq": 10},
        ]
        # Even though hello.py doesn't exist on disk, single-file → don't gate
        assert main.task_completed_heuristic(
            msgs,
            op_cmd="build hello.py",
            workspace_dir=str(tmp_path),
        ) is True


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


class TestClaimsFileWithoutCodeBlock:
    """CODE TRANSFER gate — agent claims a file but doesn't paste content."""

    def test_swedish_klar_med_without_paste(self):
        msg = "Klar med: Skapade app.py med en enkel Flask-applikation."
        assert main.claims_file_without_code_block(msg) == "app.py"

    def test_english_created_without_paste(self):
        msg = "Done with: Created models.py with the User schema."
        assert main.claims_file_without_code_block(msg) == "models.py"

    def test_modified_without_paste(self):
        assert main.claims_file_without_code_block("Modified db.py — added migration.") == "db.py"

    def test_paste_present_passes(self):
        msg = (
            "Klar med: Skapade app.py med Flask.\n"
            "```python\nfrom flask import Flask\n```"
        )
        assert main.claims_file_without_code_block(msg) is None

    def test_no_file_claim_passes(self):
        assert main.claims_file_without_code_block("Verified the API returns 200.") is None

    def test_pass_passes(self):
        assert main.claims_file_without_code_block("PASS") is None

    def test_autosummary_passes(self):
        msg = "[auto-summary] Actions this turn: ran `cat > app.py`."
        assert main.claims_file_without_code_block(msg) is None

    def test_backticked_filename_detected(self):
        msg = "Klar med: Skapade `test_app.py` med en pytest-fixture."
        assert main.claims_file_without_code_block(msg) == "test_app.py"

    def test_attribution_to_other_agent_passes(self):
        msg = "I see macmini2 created app.py with /healthz."
        assert main.claims_file_without_code_block(msg) is None

    def test_passive_have_been_created_without_paste(self):
        msg = (
            "I ran the tests and they passed successfully. "
            "Both `app.py` and `test_app.py` have been created and verified."
        )
        assert main.claims_file_without_code_block(msg) == "app.py"


class TestClaimsNonexistentFile:
    """Anti-hallucination gate — claim of created file that isn't on disk."""

    def test_hallucinated_file_detected(self, tmp_path):
        msg = "Klar med: Created test_app.py with a pytest test."
        assert main.claims_nonexistent_file(msg, str(tmp_path)) == "test_app.py"

    def test_existing_file_passes(self, tmp_path):
        (tmp_path / "test_app.py").write_text("# test\n", encoding="utf-8")
        msg = "Klar med: Created test_app.py with a pytest test."
        assert main.claims_nonexistent_file(msg, str(tmp_path)) is None

    def test_file_in_subdir_passes(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("from flask import Flask\n", encoding="utf-8")
        msg = "Done with: Created app.py with the Flask scaffold."
        assert main.claims_nonexistent_file(msg, str(tmp_path)) is None

    def test_no_claim_passes(self, tmp_path):
        assert main.claims_nonexistent_file("PASS", str(tmp_path)) is None
        assert main.claims_nonexistent_file(
            "Verified the API returns 200.", str(tmp_path),
        ) is None

    def test_autosummary_passes(self, tmp_path):
        msg = "[auto-summary] Actions this turn: ran `cat > app.py`."
        assert main.claims_nonexistent_file(msg, str(tmp_path)) is None

    def test_attribution_to_other_agent_passes(self, tmp_path):
        # "macmini2 created app.py" — not first-person, sentence doesn't start with verb
        msg = "I see macmini2 created app.py with /healthz."
        assert main.claims_nonexistent_file(msg, str(tmp_path)) is None

    def test_missing_workspace_dir_still_blocks(self, tmp_path):
        msg = "Klar med: Created models.py with User schema."
        ghost = tmp_path / "does-not-exist"
        assert main.claims_nonexistent_file(msg, str(ghost)) == "models.py"

    def test_passive_have_been_created_detected(self, tmp_path):
        msg = (
            "I ran the tests and they passed successfully. "
            "Both `app.py` and `test_app.py` have been created and verified."
        )
        assert main.claims_nonexistent_file(msg, str(tmp_path)) == "app.py"

    def test_passive_first_missing_file_returned(self, tmp_path):
        (tmp_path / "app.py").write_text("from flask import Flask\n", encoding="utf-8")
        msg = "Both `app.py` and `test_app.py` have been created."
        assert main.claims_nonexistent_file(msg, str(tmp_path)) == "test_app.py"

    def test_swedish_passive_har_skapats(self, tmp_path):
        msg = "Både `app.py` och `test_app.py` har skapats och verifierats."
        assert main.claims_nonexistent_file(msg, str(tmp_path)) == "app.py"


class TestWrittenFilesMissingPaste:
    """Gate: every file written via tools this turn must appear in a code block."""

    def test_unmentioned_written_file(self):
        reply = (
            "Done with: created `test_app.py`.\n"
            "```python\nimport pytest\nfrom app import app\n```"
        )
        written = ["app.py", "test_app.py"]
        assert main.written_files_missing_paste(reply, written) == "app.py"

    def test_all_written_files_pasted(self):
        reply = (
            "Done with: created both files.\n"
            "app.py:\n```python\nfrom flask import Flask\n```\n"
            "test_app.py:\n```python\nimport pytest\n```"
        )
        written = ["app.py", "test_app.py"]
        assert main.written_files_missing_paste(reply, written) is None

    def test_autosummary_skipped(self):
        reply = "[auto-summary] Actions this turn: ran `cat > app.py`"
        assert main.written_files_missing_paste(reply, ["app.py"]) is None

    def test_pass_skipped(self):
        assert main.written_files_missing_paste("PASS", ["app.py"]) is None

    def test_no_code_blocks_when_written(self):
        assert main.written_files_missing_paste(
            "Done with: created app.py.", ["app.py"],
        ) == "app.py"


class TestAutosummaryHelpers:
    """Auto-summary builder pastes the last-written file when small enough."""

    def test_extract_written_file_from_heredoc(self):
        assert agent._extract_written_file("cat > app.py <<'EOF'") == "app.py"
        assert agent._extract_written_file("cat >> notes.md") == "notes.md"
        assert agent._extract_written_file("printf 'x' > out.txt") == "out.txt"
        assert agent._extract_written_file("tee >> log.txt") == "log.txt"

    def test_extract_written_file_none_for_read(self):
        assert agent._extract_written_file("cat app.py") is None
        assert agent._extract_written_file("ls -la") is None

    def test_build_autosummary_pastes_small_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(agent, "WORKSPACE_DIR", str(tmp_path))
        (tmp_path / "hello.py").write_text("print('hi')\n", encoding="utf-8")
        out = agent._build_autosummary(
            ["ran `cat > hello.py`"], ["hello.py"],
        )
        assert "Klar med: `hello.py`" in out
        assert "```python" in out
        assert "print('hi')" in out

    def test_build_autosummary_splits_large_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(agent, "WORKSPACE_DIR", str(tmp_path))
        (tmp_path / "big.py").write_text("x = 1\n" * 800, encoding="utf-8")
        out = agent._build_autosummary(["ran `cat > big.py`"], ["big.py"])
        assert "big.py" in out
        assert "```" in out
        assert "part 1/" in out or len(out) > 1000

    def test_build_autosummary_no_files(self):
        assert agent._build_autosummary(["read `app.py`"], []) == "PASS"

    def test_build_autosummary_missing_file_safe(self, tmp_path, monkeypatch):
        monkeypatch.setattr(agent, "WORKSPACE_DIR", str(tmp_path))
        assert agent._build_autosummary(["edited `gone.py`"], ["gone.py"]) == "PASS"


class TestWorkspaceGap:
    def test_extract_filenames_from_operator_text(self):
        text = "Need app.py, models.py, and project_cli.py with verify.sh"
        names = main.extract_required_filenames(text)
        assert "app.py" in names
        assert "models.py" in names
        assert "project_cli.py" in names

    def test_extract_filenames_from_prose_components(self):
        # The Igor live-session case — pure prose, no .py suffixes.
        text = (
            "all agents, let's build a multiplayer quiz game in Python together. "
            "We need: question bank, scoring system, and game loop"
        )
        names = main.extract_required_filenames(text)
        assert "question_bank.py" in names
        assert "scoring_system.py" in names
        assert "game_loop.py" in names

    def test_explicit_filenames_skip_prose_fallback(self):
        # If operator names files explicitly, prose components are ignored.
        text = "Build app.py — the question bank handles input"
        names = main.extract_required_filenames(text)
        assert names == ["app.py"]

    def test_prose_fallback_strips_stop_words(self):
        text = "Please build the game loop for our project"
        names = main.extract_required_filenames(text)
        assert "game_loop.py" in names
        assert all(not n.startswith(("the_", "our_", "please_")) for n in names)

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

    def test_delegated_visible_in_ctx_not_batch(self):
        name = main.AGENT_NAME
        history = [
            {
                "agent_name": "igor-petersson-agent",
                "content": f"@{name} please implement error handling module",
            },
        ]
        batch = [{"agent_name": "oliver_agent", "content": "working on UI"}]
        assert not main.was_delegated_to_me(batch)
        assert main.was_delegated_to_me(batch, ctx=history + batch)


class TestGoRelease:
    PM = "igor-petersson-agent"

    def test_go_alone(self):
        msgs = [{"agent_name": self.PM, "content": "All agents:\nGO\n"}]
        assert main.manager_work_released(msgs, self.PM)

    def test_go_ahead_from_manager(self):
        msgs = [{"agent_name": self.PM, "content": "Go ahead and implement your tasks"}]
        assert main.manager_work_released(msgs, self.PM)

    def test_start_coding_from_manager(self):
        msgs = [{"agent_name": self.PM, "content": "Start coding — assignments above"}]
        assert main.manager_work_released(msgs, self.PM)

    def test_agent_assignment_line_from_manager(self):
        msgs = [
            {
                "agent_name": self.PM,
                "content": "- oliver_agent: Implement UI components with responsive design.",
            },
        ]
        assert main.manager_work_released(msgs, self.PM)

    def test_agent_assignment_no_release_from_random_peer(self):
        text = "- oliver_agent: Implement UI components"
        msgs = [{"agent_name": "oliver_agent", "content": text}]
        assert not main.manager_work_released(msgs, self.PM)

    def test_frozen_clears_after_go_ahead(self):
        msgs = [
            {
                "agent_name": "human:Igor",
                "content": "DO NOT START WORKING UNTIL THE MANAGER SAYS SO.",
            },
            {"agent_name": self.PM, "content": "Go ahead and implement your claimed tasks"},
        ]
        assert not main.development_frozen_by_manager(msgs, self.PM)

    def test_frozen_until_manager_assigns_in_close_msg(self):
        msgs = [
            {
                "agent_name": "human:Igor",
                "content": "DO NOT START WORKING UNTIL THE MANAGER SAYS SO.",
            },
            {
                "agent_name": self.PM,
                "content": (
                    "Roster collection concluded.\n"
                    "- oliver_agent: Implement UI components.\n"
                    "Others may claim remaining tasks once open."
                ),
            },
        ]
        assert not main.development_frozen_by_manager(msgs, self.PM)


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

    def test_allows_heredoc_with_flask_route_in_body(self):
        # Regression: URL-style paths inside a heredoc body must NOT trip
        # the absolute-path guard. The target file `backend/main.py` is
        # relative — the route string is shell-side data, not an argument.
        cmd = (
            "cat > backend/main.py <<'EOF'\n"
            "@app.route('/scrape', methods=['POST'])\n"
            "def scrape(): pass\n"
            "EOF"
        )
        assert agent.security_check(cmd) is None

    def test_allows_heredoc_unquoted_delimiter(self):
        cmd = "cat > app.py <<EOF\nprint('/tmp/foo would be a path')\nEOF"
        assert agent.security_check(cmd) is None

    def test_still_blocks_absolute_path_in_head(self):
        # The fix must not weaken the actual check — paths in the shell-arg
        # part of the command (before any heredoc) are still rejected.
        assert agent.security_check("cat /etc/passwd") is not None
        assert agent.security_check("cat > /etc/hosts <<EOF\ndata\nEOF") is not None


class TestNormalizePass:
    """`<name>: PASS`, `PASS.`, `[PASS]` etc. must collapse to bare PASS so
    the loop's `if reply == 'PASS'` check catches them and they never go to
    the hub as real messages."""

    def test_bare_pass(self):
        assert agent._normalize_pass("PASS", "marcus-local-3") == "PASS"

    def test_lowercase_pass(self):
        assert agent._normalize_pass("pass", "marcus-local-3") == "PASS"

    def test_name_prefix(self):
        # The actual misbehavior observed in marcus-local-3.log
        assert agent._normalize_pass(
            "marcus-local-3: PASS", "marcus-local-3"
        ) == "PASS"

    def test_name_prefix_case_insensitive(self):
        assert agent._normalize_pass(
            "Marcus-Local-3: pass", "marcus-local-3"
        ) == "PASS"

    def test_punctuation_variants(self):
        for variant in ("PASS.", "PASS!", "[PASS]", "(PASS)", "**PASS**", "  PASS  "):
            assert agent._normalize_pass(variant, "agent") == "PASS", variant

    def test_real_reply_unchanged(self):
        # Anything with actual content beyond a PASS sentinel must be passed
        # through verbatim.
        reply = "Klar med: implemented backend skeleton."
        assert agent._normalize_pass(reply, "marcus-local-3") == reply

    def test_pass_inside_sentence_not_normalized(self):
        reply = "Note: PASS this step over to the next agent."
        assert agent._normalize_pass(reply, "marcus-local-3") == reply

    def test_empty_reply(self):
        assert agent._normalize_pass("", "marcus-local-3") == ""


class TestReplyMentionsMissingRequired:
    """dup-ABORT bypass: send anyway if reply names a still-missing required file."""

    def test_no_op_cmd_returns_false(self, tmp_path):
        assert main.reply_mentions_missing_required(
            "Created app.py", op_cmd=None, workspace_dir=str(tmp_path),
        ) is False

    def test_no_required_files_returns_false(self, tmp_path):
        # operator command has no filenames → nothing to check
        assert main.reply_mentions_missing_required(
            "Created app.py", op_cmd="Build something nice",
            workspace_dir=str(tmp_path),
        ) is False

    def test_all_required_present_returns_false(self, tmp_path):
        (tmp_path / "app.py").write_text("x")
        (tmp_path / "db.py").write_text("x")
        assert main.reply_mentions_missing_required(
            "Created app.py",
            op_cmd="Build app.py and db.py",
            workspace_dir=str(tmp_path),
        ) is False

    def test_reply_names_missing_required_returns_true(self, tmp_path):
        # db.py exists, app.py is still missing, reply mentions app.py
        (tmp_path / "db.py").write_text("x")
        assert main.reply_mentions_missing_required(
            "Created app.py with routes",
            op_cmd="Build app.py and db.py",
            workspace_dir=str(tmp_path),
        ) is True

    def test_reply_mentions_only_done_required_returns_false(self, tmp_path):
        # db.py is the one missing, but reply mentions app.py which is present
        (tmp_path / "app.py").write_text("x")
        assert main.reply_mentions_missing_required(
            "Verified app.py runs cleanly",
            op_cmd="Build app.py and db.py",
            workspace_dir=str(tmp_path),
        ) is False

    def test_reply_mentions_unrelated_file_returns_false(self, tmp_path):
        # Reply mentions test.py which isn't in the operator spec at all
        assert main.reply_mentions_missing_required(
            "Created test.py",
            op_cmd="Build app.py and db.py",
            workspace_dir=str(tmp_path),
        ) is False


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


class TestSplitForHub:
    def test_short_message_unchanged(self):
        msg = "Hello world"
        assert main.split_for_hub(msg) == [msg]

    def test_exact_max_len_unchanged(self):
        msg = "x" * 4090
        assert main.split_for_hub(msg) == [msg]

    def test_splits_at_code_block_boundary(self):
        code = "```python\n" + "x = 1\n" * 800 + "```\n"
        rest = "More text after the block."
        full = code + rest
        assert len(full) > 4090
        chunks = main.split_for_hub(full)
        assert len(chunks) == 2
        assert "```" in chunks[0]
        assert chunks[1].startswith("(cont.)")

    def test_splits_at_newline_when_no_code_block(self):
        lines = ("A line of text.\n" * 260)
        assert len(lines) > 4090
        chunks = main.split_for_hub(lines)
        assert len(chunks) >= 2
        for chunk in chunks[:-1]:
            assert len(chunk) <= 4090

    def test_continuation_prefix_on_subsequent_chunks(self):
        long_text = "word " * 900
        chunks = main.split_for_hub(long_text)
        assert len(chunks) >= 2
        for chunk in chunks[1:]:
            assert chunk.startswith("(cont.)")

    def test_all_chunks_within_max_len(self):
        big = "```python\n" + ("y = 2\n" * 200) + "```\n" + ("z = 3\n" * 200)
        for chunk in main.split_for_hub(big):
            assert len(chunk) <= 4090

    def test_respects_hub_msg_break_boundary(self):
        # HUB_MSG_BREAK marks distinct hub messages — splitter must honor it
        a = "first message"
        b = "second message"
        combined = a + agent.HUB_MSG_BREAK + b
        assert main.split_for_hub(combined) == [a, b]

    def test_empty_pieces_filtered(self):
        # Leading or trailing breaks shouldn't produce empty hub messages
        msg = agent.HUB_MSG_BREAK + "only content" + agent.HUB_MSG_BREAK
        assert main.split_for_hub(msg) == ["only content"]


class TestFormatCodeTransfer:
    def test_small_file_single_message(self):
        out = agent.format_code_transfer("hello.py", "print('hi')\n", "python")
        assert agent.HUB_MSG_BREAK not in out
        assert "Klar med: `hello.py`" in out
        assert "(part" not in out
        assert "```python" in out
        assert "print('hi')" in out

    def test_large_file_produces_multi_part(self):
        content = "\n".join(f"line {i:04d}: " + "x" * 60 for i in range(120))
        out = agent.format_code_transfer("big.py", content, "python")
        parts = out.split(agent.HUB_MSG_BREAK)
        assert len(parts) >= 2
        # First part carries the Klar med header + (part 1/N)
        assert parts[0].startswith("Klar med: `big.py` (part 1/")
        # Subsequent parts use the rest-header form
        for i, p in enumerate(parts[1:], start=2):
            assert p.startswith(f"(part {i}/{len(parts)}) `big.py`")
        # Every hub message stays under the hub cap
        for p in parts:
            assert len(p) <= 4090

    def test_each_part_has_closed_fence(self):
        content = "\n".join(f"row {i}: data" for i in range(900))
        parts = agent.format_code_transfer("data.py", content, "python").split(
            agent.HUB_MSG_BREAK
        )
        assert len(parts) >= 2
        for p in parts:
            assert p.count("```") == 2  # opening + closing fence per chunk

    def test_long_single_line_falls_back_to_hard_cut(self):
        # No newlines anywhere — helper must still produce chunks under cap
        blob = "x" + "y" * 6000
        parts = agent.format_code_transfer("blob.js", blob, "javascript").split(
            agent.HUB_MSG_BREAK
        )
        assert len(parts) >= 2
        for p in parts:
            assert len(p) <= 4090

    def test_no_truncated_marker_emitted(self):
        # Regression: the old behavior added "(truncated — N chars total)"
        # which peers correctly flagged as incomplete. New behavior splits
        # instead, so the marker should never appear in helper output.
        content = "x = 1\n" * 2000
        out = agent.format_code_transfer("verbose.py", content, "python")
        assert "truncated" not in out.lower()


class TestCodeTransferRoundTrip:
    """End-to-end: format → split_for_hub → auto_save_peer_code → file matches."""

    @staticmethod
    def _roundtrip(tmp_path, fname, content, lang):
        msg = agent.format_code_transfer(fname, content, lang)
        chunks = main.split_for_hub(msg)
        state = AgentState(msg_cap=10, token_counter=TokenCounter(cap=10_000))
        import logging
        peer_msgs = [
            {"agent_name": "peer", "content": c, "seq": i}
            for i, c in enumerate(chunks, 1)
        ]
        main.auto_save_peer_code(
            peer_msgs, str(tmp_path), logging.getLogger("rt"), state=state,
        )
        return (tmp_path / fname).read_text(encoding="utf-8"), chunks

    def test_single_message_roundtrip(self, tmp_path):
        content = "def hello():\n    return 'world'\n"
        recon, chunks = self._roundtrip(tmp_path, "hello.py", content, "python")
        assert len(chunks) == 1
        assert recon.rstrip("\n") == content.rstrip("\n")

    def test_multi_part_roundtrip_matches_original(self, tmp_path):
        content = "\n".join(
            f"# line {i:04d} — descriptive text about the implementation"
            for i in range(120)
        )
        recon, chunks = self._roundtrip(tmp_path, "backend/main.py", content, "python")
        assert len(chunks) >= 2
        assert recon.rstrip("\n") == content.rstrip("\n")

    def test_three_part_roundtrip(self, tmp_path):
        content = "\n".join(f"row {i}: " + "x" * 60 for i in range(250))
        recon, chunks = self._roundtrip(tmp_path, "rows.py", content, "python")
        assert len(chunks) >= 3
        assert recon.rstrip("\n") == content.rstrip("\n")

    def test_blank_lines_preserved(self, tmp_path):
        # Intentional blank lines between functions must survive reassembly
        content = (
            "def a():\n    pass\n\n\n"
            "def b():\n    pass\n\n\n"
            "def c():\n" + ("    print('x')\n" * 400)
        )
        recon, chunks = self._roundtrip(tmp_path, "spaced.py", content, "python")
        assert len(chunks) >= 2
        # Triple-newline runs preserved exactly
        assert recon.count("\n\n\n") == content.count("\n\n\n")
        assert recon.rstrip("\n") == content.rstrip("\n")

    def test_partial_delivery_marks_incomplete(self, tmp_path):
        # Receiver should not write a file until all parts have arrived
        content = "\n".join(f"line {i}: data" for i in range(900))
        chunks = main.split_for_hub(
            agent.format_code_transfer("partial.py", content, "python")
        )
        assert len(chunks) >= 2
        state = AgentState(msg_cap=10, token_counter=TokenCounter(cap=10_000))
        import logging
        # Deliver everything EXCEPT the last part
        partial = [
            {"agent_name": "peer", "content": c, "seq": i}
            for i, c in enumerate(chunks[:-1], 1)
        ]
        main.auto_save_peer_code(
            partial, str(tmp_path), logging.getLogger("partial"), state=state,
        )
        assert not (tmp_path / "partial.py").exists()
        assert "incomplete split" in state.peer_file_issues.get("partial.py", "")


class TestHubDiscipline:
    @pytest.mark.parametrize("text", [
        "all agent STOP NOW",
        "All agents, stop work",
        "Please stop talking in the group chat",
        "Everyone stop posting now",
        "Agents, stop responding",
        "Do not post until I say so",
        "Be quiet all agents",
    ])
    def test_human_stop_phrasings(self, text):
        assert main.is_human_stop_directive(text)

    @pytest.mark.parametrize("text", [
        "continue again",
        "All agents, continue work",
        "you may resume posting",
        "OK to continue now everyone",
        "Erik (human): all agents proceed with work",
    ])
    def test_human_resume_phrasings(self, text):
        assert main.is_human_resume_directive(text)

    def test_peer_stop_does_not_count(self):
        assert not main.is_human_stop_directive("STOP acknowledged, pausing")

    def test_stop_then_resume_replay(self):
        msgs = [
            {"agent_name": "human:Amr", "content": "all agent STOP NOW"},
            {"agent_name": "human:Igor", "content": "All agents, continue work"},
        ]
        assert not main.apply_stop_resume_from_messages(msgs)

    def test_igor_message_not_work_directive(self):
        igor = (
            "DO NOT START WORKING UNTIL THE MANAGER SAYS SO. "
            "create a roaster with every participant."
        )
        assert not main.is_work_operator_directive(igor)

    def test_erik_claim_detected(self):
        msgs = [
            {"agent_name": "human:Igor", "content": "first one that answers is manager"},
            {"agent_name": "ErikMoren-agent", "content": "**Claiming the manager/coordination task.**"},
        ]
        assert main.resolve_peer_manager(msgs, "marcus-udd-agent") == "ErikMoren-agent"

    def test_magnus_manager_line_wins_over_erik_coordination(self):
        msgs = [
            {"agent_name": "human:Igor", "content": "first one that answers is manager"},
            {"agent_name": "ErikMoren-agent", "content": "**Claiming the coordination task.**"},
            {"agent_name": "magnus-rosman-agent", "content": "MANAGER: magnus-rosman-agent\n\nI am taking the manager role."},
            {"agent_name": "magnus-rosman-agent", "content": "DO NOT begin any development work until I say GO."},
        ]
        assert main.resolve_peer_manager(msgs, "marcus-udd-agent") == "magnus-rosman-agent"
        assert main.development_frozen_by_manager(msgs)
        assert main.roster_phase_active(
            msgs + [{"agent_name": "magnus-rosman-agent",
                       "content": "All agents: post your ROSTER entry once."}],
            "magnus-rosman-agent",
        )

    def test_erik_coordination_alone_not_manager(self):
        msgs = [{"agent_name": "ErikMoren-agent", "content": "**Claiming the coordination task.**"}]
        assert main.resolve_peer_manager(msgs, "marcus-udd-agent") is None

    def test_peer_app_py_delivery_detected(self):
        msgs = [
            {"agent_name": "ErikMoren-agent", "content": "CLAIM: create `app.py` with /healthz"},
            {"agent_name": "igor-petersson-agent", "content": "[DONE] Created `app.py`"},
        ]
        assert "app.py" in main.files_delivered_by_peers(msgs, "marcus-udd-agent")

    def test_erik_code_block_counts_as_delivery(self):
        msgs = [{
            "agent_name": "ErikMoren-agent",
            "content": "CLAIM: app.py\n```python\nfrom flask import Flask\n```",
        }]
        assert "app.py" in main.files_delivered_by_peers(msgs, "marcus-udd-agent")

    def test_sync_stop_from_history(self):
        s = AgentState(msg_cap=10, token_counter=TokenCounter(1000))
        msgs = [
            {"agent_name": "human:Amr", "content": "all agent STOP NOW"},
            {"agent_name": "human:Igor", "content": "All agents, continue work"},
        ]
        main.sync_session_flags_from_history(msgs, s, "marcus-udd-agent")
        assert not s.silence_active

    def test_stop_talking_stays_silent_until_human_continue(self):
        s = AgentState(msg_cap=10, token_counter=TokenCounter(1000))
        msgs = [{"agent_name": "human:Igor", "content": "All agents, stop talking"}]
        main.sync_session_flags_from_history(msgs, s, "marcus-udd-agent")
        assert s.silence_active
        assert main.is_human_stop_directive("stop talking please")

    def test_sync_stop_sticky_until_resume(self):
        s = AgentState(msg_cap=10, token_counter=TokenCounter(1000))
        msgs = [{"agent_name": "human:Amr", "content": "all agent STOP NOW"}]
        main.sync_session_flags_from_history(msgs, s, "marcus-udd-agent")
        assert s.silence_active

    def test_duplicate_peer_app_py_blocked(self):
        reply = "Klar med: `app.py`\n```python\nfrom flask import Flask\n```"
        assert main.would_duplicate_peer_delivery(reply, {"app.py"})

    def test_blocked_manager_reply(self):
        assert main._BLOCKED_SELF_MANAGER_RE.search("I will act as the manager")
        assert main._BLOCKED_SELF_MANAGER_RE.search("session_manager.py")

    def test_josef_step_up_manager_transcript(self):
        josef_protocol = (
            "I'll step up as manager for this session.\n\n"
            "## COMMUNICATION PROTOCOL\n"
            "All agents: reply once with your name.\n"
            "Task allocation will happen after roster is complete. "
            "No agent starts coding until I assign tasks explicitly.\n"
            "**Next step: All agents post your ROSTER entry once.**"
        )
        msgs = [
            {"agent_name": "human:Igor", "content": (
                "DO NOT START WORKING UNTIL THE MANAGER SAYS SO. "
                "The task is to create an Investment Research Firm."
            )},
            {"agent_name": "ErikMoren-agent", "content": "**Claiming the coordination task.**"},
            {"agent_name": "josef-agent", "content": josef_protocol},
            {"agent_name": "emil-hjaertfors-agent", "content": "ROSTER: emil-hjaertfors-agent | capabilities: x"},
        ]
        assert main.resolve_peer_manager(msgs, "marcus-udd-agent") == "josef-agent"
        assert main.development_frozen_by_manager(msgs)
        assert main.roster_phase_active(msgs, "josef-agent")
        assert main.is_unsolicited_roster_post(
            "ROSTER: marcus-udd-agent | capabilities: code | LLM: gemini",
            mentioned_me=False,
            delegated=False,
        )

    def test_step_up_not_coordination_only(self):
        assert main._message_claims_manager("I'll step up as manager for this session.")
        assert not main._message_claims_manager("**Claiming the coordination task.**")


class TestTrace:
    def setup_method(self):
        import trace as tr
        tr.clear()

    def test_record_and_format(self):
        import trace as tr
        tr.record("PASS", "silence active", "human STOP")
        items = tr.get_recent(5)
        assert len(items) == 1
        assert items[0]["kind"] == "PASS"
        text = tr.format_entry(items[0])
        assert "[PASS]" in text
        assert "silence" in text


class TestIgorReactSelfOrganize:
    IGOR_OP = (
        "all agents, collaboratively build a React calculator app. "
        "No predefined roles exist. No leaders, managers, architects, or testers. "
        "Self-organize, communicate, avoid duplicate work. Act autonomously. "
        "The first one that answers to this message IS the manager."
    )
    IGOR_MGR_CLAIM = (
        "[CLAIM] I claim the manager/coordinator role for this collaborative "
        "React calculator app project."
    )

    def test_work_directive_despite_manager_race(self):
        assert main.is_work_operator_directive(self.IGOR_OP)

    def test_self_organize_build_kickoff(self):
        assert main.is_broadcast_work_kickoff(self.IGOR_OP)

    def test_no_defer_when_self_organize_build(self):
        msgs = [
            {"agent_name": "human:Igor", "content": self.IGOR_OP},
            {"agent_name": "igor-petersson-agent", "content": self.IGOR_MGR_CLAIM},
        ]
        assert not main.should_defer_to_peer_manager(
            msgs,
            self.IGOR_OP,
            "igor-petersson-agent",
            "marcus-udd-agent",
            mentioned_me=False,
            delegated=False,
        )

    def test_no_defer_when_roster_roll_call_due(self):
        roster_ask = (
            "@all agents: Please post your [ROSTER] line indicating your capabilities."
        )
        msgs = [
            {"agent_name": "human:Igor", "content": self.IGOR_OP},
            {"agent_name": "igor-petersson-agent", "content": self.IGOR_MGR_CLAIM},
            {"agent_name": "igor-petersson-agent", "content": roster_ask},
        ]
        assert main.roster_roll_call_requested(msgs, "igor-petersson-agent")
        assert not main.should_defer_to_peer_manager(
            msgs,
            self.IGOR_OP,
            "igor-petersson-agent",
            "marcus-udd-agent",
            mentioned_me=False,
            delegated=False,
            roster_posted=False,
        )

    def test_defer_after_roster_posted(self):
        roster_ask = "@all agents: Please post your [ROSTER] entry once."
        msgs = [
            {"agent_name": "human:Igor", "content": self.IGOR_OP},
            {"agent_name": "igor-petersson-agent", "content": roster_ask},
            {"agent_name": "marcus-udd-agent", "content": "[ROSTER] marcus-udd-agent | SWE"},
        ]
        assert main.should_defer_to_peer_manager(
            msgs,
            self.IGOR_OP,
            "igor-petersson-agent",
            "marcus-udd-agent",
            mentioned_me=False,
            delegated=False,
            roster_posted=True,
        )

    def test_manager_coordinator_claim(self):
        assert main._message_claims_manager(self.IGOR_MGR_CLAIM)


class TestIgorManagerClaim:
    IGOR_CLAIM = (
        "[CLAIM]\n\nI claim the role of manager for this React calculator app session.\n\n"
        "[PLAN]\nI propose the following communication protocol."
    )

    def test_claim_role_of_manager_detected(self):
        assert main._message_claims_manager(self.IGOR_CLAIM)

    def test_resolve_peer_manager_from_igor_claim(self):
        msgs = [
            {"agent_name": "human:Igor", "content": "all agents, build a React calculator"},
            {"agent_name": "igor-petersson-agent", "content": self.IGOR_CLAIM},
        ]
        assert main.resolve_peer_manager(msgs, "marcus-udd-agent") == "igor-petersson-agent"

    def test_designation_from_human_emil(self):
        msgs = [
            {"agent_name": "igor-petersson-agent", "content": self.IGOR_CLAIM},
            {
                "agent_name": "human:Emil",
                "content": "all agents, listen to igor-petersson-agent that is the manager",
            },
        ]
        assert main.resolve_peer_manager(msgs, "marcus-udd-agent") == "igor-petersson-agent"

    def test_prompt_includes_peer_manager_section(self):
        prompt = main.build_active_prompt(
            "SYS",
            [],
            operator_directive=False,
            op_cmd=None,
            mentioned_me=False,
            peer_manager="igor-petersson-agent",
        )
        assert "PEER MANAGER ACTIVE: igor-petersson-agent" in prompt


class TestBroadcastKickoff:
    INVESTMENT_IGOR = (
        "All agents: The task is to create an Investment Research Firm Goal. "
        "Generate investment theses and portfolio recommendations."
    )

    def test_kickoff_true_for_investment_broadcast(self):
        assert main.is_broadcast_work_kickoff(self.INVESTMENT_IGOR)

    def test_kickoff_false_for_roster_broadcast(self):
        assert not main.is_broadcast_work_kickoff(
            "All agents post your ROSTER entry once.",
        )

    def test_kickoff_false_for_manager_race(self):
        cmd = (
            "DO NOT START WORKING UNTIL THE MANAGER SAYS SO. "
            "The task is to create an Investment Research Firm."
        )
        assert not main.is_broadcast_work_kickoff(cmd)

    def test_build_active_prompt_includes_kickoff_section(self):
        prompt = main.build_active_prompt(
            "SYS",
            [],
            operator_directive=True,
            op_cmd=self.INVESTMENT_IGOR,
            mentioned_me=False,
        )
        assert "BROADCAST COLLABORATION KICKOFF" in prompt

    def test_peer_overlap_does_not_block_kickoff_without_explicit_files(self):
        op = self.INVESTMENT_IGOR
        peer_done = {"investment_research_firm_goal.md"}
        assert not main.peer_overlap_blocks_turn(
            op, peer_done, mentioned_me=False,
        )

    def test_peer_overlap_blocks_when_explicit_files_all_delivered(self):
        op = "All agents: build app.py and README.md together"
        peer_done = {"app.py", "README.md"}
        assert main.peer_overlap_blocks_turn(op, peer_done, mentioned_me=False)

    def test_kickoff_claim_fallback_under_200_chars(self):
        claim = main.build_broadcast_kickoff_claim(
            self.INVESTMENT_IGOR,
            [{"agent_name": "emil-hjaertfors-agent", "content": (
                "Klar med: `investment_research_firm_goal.md`"
            )}],
            "/tmp",
            "marcus-udd-agent",
        )
        assert claim.startswith("[CLAIM]")
        assert len(claim) <= 200


class TestColonAddressRouting:
    def test_agent_name_with_hyphen_matches(self):
        assert main._COLON_ADDRESS_RE.match("emil-flyghed-agent: please add subtract")
        assert main._COLON_ADDRESS_RE.match("magnus-swe: can you verify?")
        assert main._COLON_ADDRESS_RE.match("hassan-swe-agent: do this")

    def test_at_prefix_not_caught_by_colon_re(self):
        assert not main._COLON_ADDRESS_RE.match("@emil-flyghed-agent please help")

    def test_single_word_not_caught(self):
        assert not main._COLON_ADDRESS_RE.match("Status: everything is done")
        assert not main._COLON_ADDRESS_RE.match("Update: tests pass")
        assert not main._COLON_ADDRESS_RE.match("agent1: task here")

    def test_all_agents_not_caught(self):
        assert not main._COLON_ADDRESS_RE.match("All agents: please build the app")


# ---------------------------------------------------------------------------
# Pinned "important messages" memory (Part 3 — survives history trimming)
# ---------------------------------------------------------------------------
class TestPinnedMemory:
    def _state(self):
        return AgentState(msg_cap=10, token_counter=TokenCounter(1000))

    def test_captures_delivery_and_claim(self):
        s = self._state()
        with patch.object(main, "AGENT_NAME", "marcus-mac"):
            main.update_pinned_memory(s, [
                {"agent_name": "bob", "content": "Klar med: `app.py` — funkar"},
                {"agent_name": "eve", "content": "Taking: backend API"},
            ])
        assert "bob delivered: app.py" in s.pinned_memory
        assert "eve claimed: backend API" in s.pinned_memory

    def test_dedupes(self):
        s = self._state()
        msg = [{"agent_name": "bob", "content": "Done with: parser.py"}]
        with patch.object(main, "AGENT_NAME", "marcus-mac"):
            main.update_pinned_memory(s, msg)
            main.update_pinned_memory(s, msg)
        assert s.pinned_memory.count("bob delivered: parser.py") == 1

    def test_caps_to_eight_keeping_recent(self):
        s = self._state()
        msgs = [{"agent_name": f"a{i}", "content": f"Taking: task{i}"} for i in range(12)]
        with patch.object(main, "AGENT_NAME", "marcus-mac"):
            main.update_pinned_memory(s, msgs)
        assert len(s.pinned_memory) == 8
        assert "a11 claimed: task11" in s.pinned_memory
        assert "a0 claimed: task0" not in s.pinned_memory

    def test_direct_mention_pinned(self):
        s = self._state()
        with patch.object(main, "AGENT_NAME", "marcus-mac"):
            main.update_pinned_memory(s, [
                {"agent_name": "bob", "content": "@marcus-mac can you take the CLI parser?"},
            ])
        assert any("→ you" in x for x in s.pinned_memory)

    def test_block_rendered_in_active_prompt(self):
        p = main.build_active_prompt(
            "SYS", [], operator_directive=False, op_cmd=None,
            mentioned_me=False, pinned_memory=["bob delivered: app.py"],
        )
        assert "SESSION MEMORY" in p
        assert "bob delivered: app.py" in p


# ---------------------------------------------------------------------------
# Private steering (console `steer` command → group-chat behaviour)
# ---------------------------------------------------------------------------
class TestPrivateSteer:
    def test_steer_injected(self):
        p = main.build_active_prompt(
            "SYS", [], operator_directive=False, op_cmd=None,
            mentioned_me=False, private_steer="focus on writing tests",
        )
        assert "PRIVATE STEERING" in p
        assert "focus on writing tests" in p

    def test_no_steer_no_section(self):
        p = main.build_active_prompt(
            "SYS", [], operator_directive=False, op_cmd=None, mentioned_me=False,
        )
        assert "PRIVATE STEERING" not in p


# ---------------------------------------------------------------------------
# Runtime config-reload (live calibration without restart)
# ---------------------------------------------------------------------------
class TestReloadRuntime:
    def test_runtime_json_applied(self, tmp_path):
        rj = tmp_path / "runtime.json"
        rj.write_text('{"msg_cap": 3, "token_cap": 12345, '
                      '"response_delay": 7, "poll_interval": 9}')
        s = AgentState(msg_cap=10, token_counter=TokenCounter(1000))
        log = MagicMock()
        orig_rd, orig_pi = main.RESPONSE_DELAY, main.POLL_INTERVAL
        try:
            with patch.object(main, "_RUNTIME_CONFIG_PATH", rj), \
                 patch.object(main, "_SYSTEM_PROMPT_PATH", tmp_path / "missing.txt"):
                main.reload_runtime(s, "OLD", 0.0, log)
            assert s.msg_cap == 3
            assert s.token_counter.cap == 12345
            assert main.RESPONSE_DELAY == 7
            assert main.POLL_INTERVAL == 9
        finally:
            main.RESPONSE_DELAY, main.POLL_INTERVAL = orig_rd, orig_pi

    def test_prompt_reloaded_only_on_mtime_change(self, tmp_path):
        sp = tmp_path / "system_prompt.txt"
        sp.write_text("X")
        mtime0 = sp.stat().st_mtime
        s = AgentState(msg_cap=10, token_counter=TokenCounter(1000))
        log = MagicMock()
        with patch.object(main, "_SYSTEM_PROMPT_PATH", sp), \
             patch.object(main, "_RUNTIME_CONFIG_PATH", tmp_path / "none.json"), \
             patch.object(main.ag, "load_system_prompt", return_value="RELOADED") as m:
            prompt, _ = main.reload_runtime(s, "OLD", mtime0, log)
            assert prompt == "OLD"
            m.assert_not_called()
            prompt2, _ = main.reload_runtime(s, "OLD", mtime0 - 100, log)
            assert prompt2 == "RELOADED"
            m.assert_called_once()


class TestIgorRosterTranscript:
    GRADER_OP = (
        "IMPORTANT: NEVER ACKNOWLEDGE ANYTHING THAT IS NOT CLEARLY INTENDED FOR YOU. "
        "first one that answers IS the manager. DO NOT START WORKING UNTIL THE MANAGER SAYS SO."
    )
    IGOR_REACT = (
        "all agents, collaboratively build a React calculator app with add, subtract, "
        "multiply, divide. Act autonomously."
    )
    IGOR_CLAIM = (
        "[CLAIM] I claim the manager role for this session to establish a "
        "communication and collaboration protocol."
    )
    IGOR_ROSTER_ASK = (
        "@all agents: Please post your [ROSTER] line indicating your capabilities"
    )
    OLIVER_ROSTER = "[ROSTER] oliver_agent | SWE specialist | tools: read_file"

    def test_peer_mgr_from_history_not_batch_only(self):
        history = [
            {"seq": 2, "agent_name": "igor-petersson-agent", "content": self.IGOR_CLAIM},
        ]
        batch = [{"seq": 10, "agent_name": "oliver_agent", "content": self.OLIVER_ROSTER}]
        ctx = history + batch
        assert main.resolve_peer_manager(ctx, "marcus-udd-agent") == "igor-petersson-agent"

    def test_roster_roll_call_requested_igor_wording(self):
        ctx = [{"agent_name": "igor-petersson-agent", "content": self.IGOR_ROSTER_ASK}]
        assert main.roster_roll_call_requested(ctx, "igor-petersson-agent")

    def test_roster_response_due_before_post(self):
        ctx = [
            {
                "agent_name": "human:Igor",
                "content": self.IGOR_REACT + " DO NOT START WORKING UNTIL THE MANAGER SAYS SO.",
            },
            {"agent_name": "igor-petersson-agent", "content": self.IGOR_CLAIM},
            {"agent_name": "igor-petersson-agent", "content": self.IGOR_ROSTER_ASK},
        ]
        assert main.development_frozen_by_manager(ctx)
        assert main.roster_response_due(
            ctx, "igor-petersson-agent", "marcus-udd-agent", roster_posted=False,
        )

    def test_no_roster_due_after_self_post_in_history(self):
        ctx = [
            {"agent_name": "igor-petersson-agent", "content": self.IGOR_ROSTER_ASK},
            {"agent_name": "marcus-udd-agent", "content": main.build_canned_roster_line("marcus-udd-agent")},
        ]
        assert not main.roster_response_due(
            ctx, "igor-petersson-agent", "marcus-udd-agent", roster_posted=False,
        )

    def test_best_work_operator_prefers_react_over_grader(self):
        ctx = [
            {"agent_name": "human:Grader", "content": self.GRADER_OP},
            {"agent_name": "human:Igor", "content": self.IGOR_REACT},
        ]
        best = main.best_work_operator_command(ctx) or ""
        assert main._WORK_OPERATOR_BODY_RE.search(best)

    def test_resolve_op_cmd_work_over_grader_sticky(self):
        op_cmd, is_work = main.resolve_op_cmd(self.GRADER_OP, None, work_cmd=self.IGOR_REACT)
        assert is_work
        assert "React calculator" in (op_cmd or "")

    def test_canned_roster_line(self):
        line = main.build_canned_roster_line("marcus-udd-agent")
        assert line.startswith("[ROSTER] marcus-udd-agent")
        assert "tools:" in line

    def test_unsolicited_roster_blocked_solicited_allowed(self):
        assert main.is_unsolicited_roster_post(
            "[ROSTER] marcus-udd-agent | SWE",
            mentioned_me=False,
            delegated=False,
            solicited=False,
        )
        assert not main.is_unsolicited_roster_post(
            "[ROSTER] marcus-udd-agent | SWE",
            mentioned_me=False,
            delegated=False,
            solicited=True,
        )

    IGOR_PLAN2 = (
        "Next step: Request roster/capabilities lines from all agents to proceed "
        "with task allocation."
    )
    IGOR_WAITING = (
        "[ROSTER] igor-petersson-agent | SWE agent | backend: gpt-4.1-mini\n\n"
        "Oliver_agent: roster received. Waiting for more roster lines before "
        "starting task allocation."
    )
    IGOR_CLOSE = (
        "[MANAGER] Roster collection concluded. Current agents available:\n"
        "- igor-petersson-agent (Manager)\n"
        "- oliver_agent (Frontend React, JS/TS, testing)\n\n"
        "Task breakdown for the React calculator app:\n"
        "1. UI implementation (responsive buttons, display, layout)\n"
        "2. Calculator operations logic (add, subtract, multiply, divide, decimals)\n"
        "3. Error handling for invalid inputs and divide-by-zero\n"
        "4. Clear/reset functionality\n"
        "5. Testing for edge cases and component integration\n\n"
        "Assignment:\n"
        "- oliver_agent: Implement UI components of the calculator with responsive design.\n\n"
        "Others may claim remaining tasks once open.\n\n"
        "Reminder: Only respond or claim tasks explicitly assigned or initiated by the manager."
    )

    def test_igor_plan2_triggers_roll_call(self):
        ctx = [
            {"agent_name": "igor-petersson-agent", "content": self.IGOR_CLAIM},
            {"agent_name": "igor-petersson-agent", "content": self.IGOR_PLAN2},
        ]
        assert main.roster_roll_call_requested(ctx, "igor-petersson-agent")

    def test_igor_waiting_more_roster_due(self):
        ctx = [
            {"agent_name": "igor-petersson-agent", "content": self.IGOR_PLAN2},
            {"agent_name": "igor-petersson-agent", "content": self.IGOR_WAITING},
        ]
        assert main.roster_response_due(
            ctx, "igor-petersson-agent", "marcus-udd-agent", roster_posted=False,
        )

    def test_roster_closed_stops_roster_due(self):
        ctx = [
            {"agent_name": "igor-petersson-agent", "content": self.IGOR_PLAN2},
            {"agent_name": "igor-petersson-agent", "content": self.IGOR_CLOSE},
        ]
        assert main.roster_collection_closed(ctx)
        assert not main.roster_response_due(
            ctx, "igor-petersson-agent", "marcus-udd-agent", roster_posted=False,
        )

    def test_open_claim_due_after_close(self):
        ctx = [
            {"agent_name": "igor-petersson-agent", "content": self.IGOR_CLOSE},
        ]
        assert main.manager_open_claim_due(
            ctx, "igor-petersson-agent", "marcus-udd-agent", claim_posted=False,
        )
        assert not main.should_defer_to_peer_manager(
            ctx,
            self.IGOR_REACT,
            "igor-petersson-agent",
            "marcus-udd-agent",
            mentioned_me=False,
            delegated=False,
            roster_posted=True,
            claim_posted=False,
        )

    def test_roster_phase_inactive_after_close(self):
        ctx = [
            {"agent_name": "igor-petersson-agent", "content": self.IGOR_WAITING},
            {"agent_name": "igor-petersson-agent", "content": self.IGOR_CLOSE},
        ]
        assert not main.roster_phase_active(ctx, "igor-petersson-agent")

    def test_claim_line_picks_operations_not_ui(self):
        line = main.build_open_task_claim_line(
            [{"agent_name": "igor-petersson-agent", "content": self.IGOR_CLOSE}],
            "igor-petersson-agent",
            "marcus-udd-agent",
        )
        assert "operations logic" in line.lower()
        assert "ui implementation" not in line.lower()
