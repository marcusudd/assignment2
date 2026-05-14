import pytest

import main
from main import (
    parse_thought,
    parse_action,
    parse_answer,
    run_agent,
    validate_startup,
)


# ============================================================
# parse_thought
# ============================================================

class TestParseThought:
    def test_extracts_content(self):
        assert parse_thought("<thought>hello</thought>") == "hello"

    def test_strips_whitespace(self):
        assert parse_thought("<thought>  trimmed  </thought>") == "trimmed"

    def test_multiline(self):
        text = "<thought>\nline1\nline2\n</thought>"
        assert parse_thought(text) == "line1\nline2"

    def test_missing_tag_returns_none(self):
        assert parse_thought("no tags here") is None

    def test_returns_first_match(self):
        text = "<thought>first</thought><thought>second</thought>"
        assert parse_thought(text) == "first"


# ============================================================
# parse_action
# ============================================================

class TestParseAction:
    VALID = "<action><tool>bash</tool><input>ls</input></action>"

    def test_returns_dict(self):
        assert parse_action(self.VALID) == {"tool": "bash", "input": "ls"}

    def test_multiline_input(self):
        text = "<action><tool>bash</tool><input>echo 'hello'\n</input></action>"
        assert parse_action(text)["input"] == "echo 'hello'"

    def test_missing_action_tag_returns_none(self):
        assert parse_action("no action here") is None

    def test_missing_tool_returns_none(self):
        assert parse_action("<action><input>ls</input></action>") is None

    def test_missing_input_returns_none(self):
        assert parse_action("<action><tool>bash</tool></action>") is None

    def test_action_alongside_answer_still_parsed(self):
        text = "<action><tool>bash</tool><input>ls</input></action><answer>done</answer>"
        assert parse_action(text) == {"tool": "bash", "input": "ls"}

    def test_full_react_format(self):
        text = (
            "<thought>I should list files</thought>\n"
            "<action>\n<tool>bash</tool>\n<input>ls /app/workspace</input>\n</action>"
        )
        result = parse_action(text)
        assert result == {"tool": "bash", "input": "ls /app/workspace"}


# ============================================================
# parse_answer
# ============================================================

class TestParseAnswer:
    def test_extracts_content(self):
        assert parse_answer("<answer>done</answer>") == "done"

    def test_strips_whitespace(self):
        assert parse_answer("<answer>  trimmed  </answer>") == "trimmed"

    def test_multiline(self):
        text = "<answer>\nline1\nline2\n</answer>"
        assert parse_answer(text) == "line1\nline2"

    def test_missing_tag_returns_none(self):
        assert parse_answer("no answer here") is None

    def test_markdown_in_answer(self):
        text = "<answer>Here is the result:\n```python\nprint('hi')\n```</answer>"
        assert "```python" in parse_answer(text)


# ============================================================
# run_agent history rollback
# ============================================================

class TestRunAgentHistoryRollback:
    def test_api_error_rolls_back_history(self, monkeypatch):
        monkeypatch.setattr(main, "call_llm", lambda msgs, prompt: ("API down", "error"))
        history = []
        result = run_agent("test question", history, "system prompt")
        assert "API error" in result
        assert len(history) == 0

    def test_max_tokens_rolls_back_history(self, monkeypatch):
        monkeypatch.setattr(main, "call_llm", lambda msgs, prompt: ("", "max_tokens"))
        history = []
        result = run_agent("test question", history, "system prompt")
        assert "max tokens" in result.lower()
        assert len(history) == 0

    def test_successful_answer_preserves_history(self, monkeypatch):
        monkeypatch.setattr(
            main, "call_llm",
            lambda msgs, prompt: ("<thought>ok</thought><answer>done</answer>", "end_turn"),
        )
        history = []
        result = run_agent("test question", history, "system prompt")
        assert result == "done"
        assert len(history) == 2
        assert history[0] == {"role": "user", "content": "test question"}
        assert history[1]["role"] == "assistant"

    def test_max_rounds_rolls_back_trailing_observation(self, monkeypatch):
        monkeypatch.setattr(main, "MAX_ROUNDS", 2)
        monkeypatch.setattr(
            main, "call_llm",
            lambda msgs, prompt: ("<action><tool>bash</tool><input>ls</input></action>", "end_turn"),
        )
        monkeypatch.setattr(main, "execute_command", lambda cmd: "file.txt")
        history = []
        result = run_agent("do stuff", history, "system prompt")
        assert "maximum rounds" in result
        assert history[-1]["role"] != "user"

    def test_second_call_after_error_does_not_corrupt_history(self, monkeypatch):
        calls = [0]

        def mock_llm(msgs, prompt):
            calls[0] += 1
            if calls[0] == 1:
                return ("API down", "error")
            return ("<answer>recovered</answer>", "end_turn")

        monkeypatch.setattr(main, "call_llm", mock_llm)
        history = []
        run_agent("first question", history, "system prompt")
        result = run_agent("second question", history, "system prompt")
        assert result == "recovered"
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "assistant"


# ============================================================
# validate_startup
# ============================================================

class TestValidateStartup:
    def test_missing_system_prompt_raises(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(main, "WORKSPACE_DIR", str(tmp_path / "workspace"))
        with pytest.raises(SystemExit):
            validate_startup()

    def test_all_present_no_error(self, tmp_path, monkeypatch):
        (tmp_path / "system_prompt.txt").write_text("prompt")
        (tmp_path / "workspace").mkdir()
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(main, "WORKSPACE_DIR", str(tmp_path / "workspace"))
        validate_startup()  # should not raise

    def test_missing_workspace_is_created(self, tmp_path, monkeypatch):
        (tmp_path / "system_prompt.txt").write_text("prompt")
        workspace = tmp_path / "workspace"
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(main, "WORKSPACE_DIR", str(workspace))
        validate_startup()
        assert workspace.exists()
