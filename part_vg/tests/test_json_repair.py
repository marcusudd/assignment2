"""Tests for repair_tool_arguments and write_file tool."""
import tempfile
from pathlib import Path

from subagent import repair_tool_arguments
from tools import dispatch_tool, tool_edit_file, tool_write_file


def test_repair_trailing_comma():
    raw = '{"path": "a.py", "content": "x",}'
    got = repair_tool_arguments(raw)
    assert got == {"path": "a.py", "content": "x"}


def test_repair_markdown_fence():
    raw = '```json\n{"path": "b.py", "content": "hi"}\n```'
    got = repair_tool_arguments(raw)
    assert got == {"path": "b.py", "content": "hi"}


def test_repair_literal_eval_fallback():
    raw = "{'path': 'c.py', 'content': 'ok'}"
    got = repair_tool_arguments(raw)
    assert got == {"path": "c.py", "content": "ok"}


def test_repair_returns_none_on_garbage():
    assert repair_tool_arguments("not json at all {{{") is None


def test_write_file_creates_file():
    with tempfile.TemporaryDirectory() as ws:
        out = tool_write_file("foo.py", "print(1)\n", ws)
        assert out.startswith("OK: created")
        assert (Path(ws) / "foo.py").read_text() == "print(1)\n"


def test_edit_file_rejects_empty_old_str_for_create():
    with tempfile.TemporaryDirectory() as ws:
        out = tool_edit_file("bar.py", "", "body", ws)
        assert "write_file" in out
        assert not (Path(ws) / "bar.py").exists()


def test_dispatch_write_file():
    with tempfile.TemporaryDirectory() as ws:
        out = dispatch_tool(
            "write_file",
            {"path": "z.py", "content": "# z"},
            workspace_dir=ws,
        )
        assert out.startswith("OK:")
        assert (Path(ws) / "z.py").read_text() == "# z"
