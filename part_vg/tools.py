"""
Tool implementations — adapted from part_3/agent.py.
workspace_dir is a parameter (not a global) so each SubAgent can use its own.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from security import resolve_path, security_check


def _subprocess_env() -> dict:
    """Make `python3`/`pytest` in the workspace resolve to Bifrost's interpreter.

    Locally, Bifrost runs inside a venv that has the demo deps (fastapi,
    sqlalchemy, pytest); the workspace subprocess otherwise inherits PATH and
    `python3` points at the system Python without those deps. Prepending the
    interpreter's bin dir fixes that. In Docker there is no venv (deps are
    global) so this is a no-op.
    """
    env = dict(os.environ)
    in_venv = sys.prefix != sys.base_prefix
    if in_venv:
        bin_dir = str(Path(sys.executable).parent)
        env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
    return env

# OpenAI-style tool schema sent to the LLM
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": (
                "Run ONE bash command. The process cwd is ALREADY the workspace "
                "root — never prefix with cd or use &&, ||, ;, |, &. "
                "No pipes (| head, | grep). No command chains with &&. "
                "Good: python3 -m pytest tests/test_x.py -x -q. "
                "Bad: cd workspace && python3 .... Bad: find . | head. "
                "Output is capped — use targeted commands."
            ),
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file (path relative to workspace). Output is capped.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Create or overwrite a file with full content. Prefer this for new files "
                "instead of edit_file. Path is relative to workspace."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": (
                "Replace an exact section of an EXISTING file. old_str must match verbatim. "
                "Use read_file first. For new files use write_file, not edit_file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_str": {"type": "string"},
                    "new_str": {"type": "string"},
                },
                "required": ["path", "old_str", "new_str"],
            },
        },
    },
]


def tool_bash(
    command: str,
    workspace_dir: str,
    max_output: int = 5000,
    auto_approve: bool = True,
) -> str:
    reason = security_check(command, workspace_dir)
    if reason:
        msg = f"BLOCKED ({reason}). Do not repeat this command shape."
        if reason in ("shell command separator", "background execution"):
            ws = Path(workspace_dir).resolve()
            msg += (
                f" Shell cwd is already {ws}. "
                "Use pipes (|), &&, or || if needed — avoid shell ; and trailing &."
            )
        return msg
    if not auto_approve:
        print(f"\n🔧 bash: {command}")
        answer = input("   Execute? (y/n): ").strip().lower()
        if answer != "y":
            return "USER DENIED: command was not executed."
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=workspace_dir,
            env=_subprocess_env(),
        )
        output = result.stdout
        if result.stderr:
            output += f"\nSTDERR: {result.stderr}"
        if result.returncode != 0:
            output += f"\nEXIT CODE: {result.returncode}"
        if not output.strip():
            return "(no output)"
        if len(output) > max_output:
            return output[:max_output] + f"\n...(truncated at {max_output} chars)"
        return output
    except subprocess.TimeoutExpired:
        return "ERROR: command timed out after 30 seconds."
    except Exception as e:
        return f"ERROR: {e}"


def tool_read_file(path: str, workspace_dir: str, max_output: int = 5000) -> str:
    target = resolve_path(path, workspace_dir)
    if target is None:
        return "ERROR: path is outside the workspace directory."
    if target.name == ".env" or str(target).endswith(".env"):
        return "ERROR: reading .env files is not allowed."
    if not target.exists():
        return f"ERROR: file not found: {path}"
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
        if len(content) > max_output:
            return content[:max_output] + f"\n...(truncated at {max_output} chars)"
        return content
    except Exception as e:
        return f"ERROR: {e}"


def tool_write_file(path: str, content: str, workspace_dir: str) -> str:
    target = resolve_path(path, workspace_dir)
    if target is None:
        return "ERROR: path is outside the workspace directory."
    try:
        existed = target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"OK: {'updated' if existed else 'created'} {path}"
    except Exception as e:
        return f"ERROR: {e}"


def tool_edit_file(
    path: str, old_str: str, new_str: str, workspace_dir: str
) -> str:
    target = resolve_path(path, workspace_dir)
    if target is None:
        return "ERROR: path is outside the workspace directory."
    try:
        if old_str == "":
            return (
                "ERROR: use write_file to create or overwrite a whole file; "
                "edit_file is for section edits on existing files."
            )
        if not target.exists():
            return f"ERROR: file not found: {path}"
        content = target.read_text(encoding="utf-8", errors="replace")
        if old_str not in content:
            return "ERROR: old_str not found — use read_file to verify exact content."
        if content.count(old_str) > 1:
            return "ERROR: old_str matches multiple locations — add more context."
        updated = content.replace(old_str, new_str, 1)
        target.write_text(updated, encoding="utf-8")
        return f"OK: replaced 1 occurrence in {path}"
    except Exception as e:
        return f"ERROR: {e}"


def dispatch_tool(
    name: str,
    inputs: dict,
    workspace_dir: str,
    max_output: int = 5000,
    auto_approve: bool = True,
) -> str:
    try:
        if name == "bash":
            return tool_bash(inputs["command"], workspace_dir, max_output, auto_approve)
        if name == "read_file":
            return tool_read_file(inputs["path"], workspace_dir, max_output)
        if name == "write_file":
            return tool_write_file(inputs["path"], inputs["content"], workspace_dir)
        if name == "edit_file":
            return tool_edit_file(
                inputs["path"], inputs["old_str"], inputs["new_str"], workspace_dir
            )
        return f"ERROR: unknown tool '{name}'"
    except KeyError as e:
        return f"ERROR: missing argument {e} for tool '{name}'"
    except Exception as e:
        return f"ERROR: tool '{name}' failed: {e}"
