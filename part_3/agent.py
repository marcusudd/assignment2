"""
Agent decision layer — wraps the Part 2 LLM + tool loop for group-chat use.
"""

import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

from openai import OpenAI, APIError


class BashApproval:
    """Routes bash y/n through the console thread to avoid stdin race conditions."""
    def __init__(self) -> None:
        self._event = threading.Event()
        self._result = "n"
        self.pending = False

    def request(self) -> str:
        self.pending = True
        self._event.clear()
        self._event.wait(timeout=60)
        self.pending = False
        return self._result

    def respond(self, answer: str) -> None:
        self._result = answer
        self._event.set()


bash_approval = BashApproval()

MODEL = os.getenv("MODEL", "anthropic/claude-sonnet-4-6")
WORKSPACE_DIR = os.getenv("WORKSPACE_DIR", "./workspace")
MAX_OUTPUT = int(os.getenv("MAX_OUTPUT", "5000"))
MAX_ROUNDS = int(os.getenv("MAX_ROUNDS", "10"))
DEBUG = os.getenv("DEBUG", "").lower() in ("1", "true")
AUTO_APPROVE = os.getenv("AUTO_APPROVE", "false").lower() in ("1", "true")
AGENT_NAME = os.getenv("AGENT_NAME", "mini_me1")

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": (
                f"Run a single bash command in the workspace. "
                f"No chaining with ;, &&, ||, |, or &. "
                f"Output is capped at {MAX_OUTPUT} chars."
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
            "description": f"Read a file relative to the workspace. Capped at {MAX_OUTPUT} chars.",
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
            "name": "edit_file",
            "description": (
                "Replace an exact section of a file. old_str must match verbatim. "
                "Returns error if not found or ambiguous. Use read_file first."
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

# ---------------------------------------------------------------------------
# Security guard (identical to Part 2)
# ---------------------------------------------------------------------------
_BLOCKED: list[tuple[str, str]] = [
    (r"(?:^|[^|&])(&&|\|\||;|&|\|)(?:[^|&]|$)", "command chaining"),
    (r"\brm\b.*-[rRfF]", "recursive/force delete"),
    (r"\bdd\b", "dd command"),
    (r"\bmkfs\b", "filesystem format"),
    (r">\s*/dev/", "write to device"),
    (r":\s*\(\s*\)\s*\{", "fork bomb"),
    (r"\bsudo\b", "sudo"),
    (r"\bsu\b(?:\s|$)", "su"),
    (r"\b(?:pkexec|doas|run0)\b", "privilege escalation"),
    (r"\b(?:shutdown|reboot|halt|poweroff)\b", "system power command"),
    (r"(?:curl|wget)\b.*\|\s*(?:ba)?sh", "remote code execution"),
    (r"(?:curl|wget)\b.*>\s*\S+\.sh\b", "downloading shell scripts"),
    (r"\bnc\b(?:\s|$)|\bnetcat\b", "netcat"),
    (r"(?:cat|less|head|tail|more)\b.*\.env\b", "reading secrets file"),
    (r"\benv\b(?:\s|$)", "environment variable dump"),
    (r"\bprintenv\b", "environment variable dump"),
    (r"\$\{?(?:OPENROUTER_API_KEY|ANTHROPIC_API_KEY|API_KEY|SECRET|PASSWORD|TOKEN|PRIVATE_KEY)\}?",
     "secret variable expansion"),
    (r"(?:^|\s|['\"`])~[/\s~]|(?:^|\s|['\"`])~$", "home directory access"),
]

_ALLOWED_ABS_PREFIXES: tuple[str, ...] = (
    "/usr/", "/bin/", "/sbin/", "/lib/", "/opt/", "/tmp/", "/dev/null",
)


def _has_external_path(command: str) -> bool:
    workspace = str(Path(WORKSPACE_DIR).resolve())
    for m in re.finditer(r'(?:^|\s|[\'"`])(\/[^\s\'"`|&;,<>]+)', command):
        path = m.group(1)
        if path.startswith(workspace):
            continue
        if any(path.startswith(p) for p in _ALLOWED_ABS_PREFIXES):
            continue
        return True
    return False


def security_check(command: str) -> str | None:
    for pattern, reason in _BLOCKED:
        if re.search(pattern, command, re.IGNORECASE):
            return reason
    if _has_external_path(command):
        return "absolute path outside workspace"
    return None


def resolve_path(rel_path: str) -> Path | None:
    workspace = Path(WORKSPACE_DIR).resolve()
    target = (workspace / rel_path).resolve()
    if not str(target).startswith(str(workspace)):
        return None
    return target


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------
def tool_bash(command: str) -> str:
    reason = security_check(command)
    if reason:
        return f"BLOCKED ({reason}). Revise the command and try again."
    if AUTO_APPROVE:
        print(f"\n🔧 bash (auto): {command}")
    else:
        print(f"\n🔧 bash: {command}")
        print("   Execute? Type 'y' or 'n' in the console:")
        if bash_approval.request() != "y":
            return "USER DENIED: command was not executed."
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=30, cwd=WORKSPACE_DIR,
        )
        output = result.stdout
        if result.stderr:
            output += f"\nSTDERR: {result.stderr}"
        if result.returncode != 0:
            output += f"\nEXIT CODE: {result.returncode}"
        if not output.strip():
            return "(no output)"
        return output[:MAX_OUTPUT] + (f"\n...(truncated)" if len(output) > MAX_OUTPUT else "")
    except subprocess.TimeoutExpired:
        return "ERROR: timed out."
    except Exception as e:
        return f"ERROR: {e}"


def tool_read_file(path: str) -> str:
    target = resolve_path(path)
    if target is None:
        return "ERROR: path is outside the workspace directory."
    if not target.exists():
        return f"ERROR: file not found: {path}"
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
        if len(content) > MAX_OUTPUT:
            return content[:MAX_OUTPUT] + f"\n...(truncated at {MAX_OUTPUT} chars)"
        return content
    except Exception as e:
        return f"ERROR: {e}"


def tool_edit_file(path: str, old_str: str, new_str: str) -> str:
    target = resolve_path(path)
    if target is None:
        return "ERROR: path is outside the workspace directory."
    if not target.exists():
        return f"ERROR: file not found: {path}"
    try:
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


def dispatch_tool(name: str, inputs: dict) -> str:
    if name == "bash":
        return tool_bash(inputs["command"])
    if name == "read_file":
        return tool_read_file(inputs["path"])
    if name == "edit_file":
        return tool_edit_file(inputs["path"], inputs["old_str"], inputs["new_str"])
    return f"ERROR: unknown tool '{name}'"


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------
def _call_llm(messages: list, system_prompt: str):
    all_messages = [{"role": "system", "content": system_prompt}] + messages
    try:
        return OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY"),
        ).chat.completions.create(
            model=MODEL,
            max_tokens=1024,
            tools=TOOLS,
            messages=all_messages,
        )
    except APIError as e:
        print(f"[API error] {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Decide: PASS or a reply string
# ---------------------------------------------------------------------------
def decide(
    new_messages: list[dict],
    own_name: str,
    system_prompt: str,
    history: list,
    token_counter: "TokenCounter",
) -> str:
    """
    Given new hub messages, return either 'PASS' or a reply string.
    May call tools before composing the reply.
    Tracks token usage via token_counter.
    """
    # Self-echo guard: if the last 3 messages are all from us, force PASS
    if len(new_messages) >= 3 and all(m["agent_name"] == own_name for m in new_messages[-3:]):
        return "PASS"

    # Build conversation context from recent hub messages
    context_lines = []
    for msg in new_messages[-20:]:
        context_lines.append(f"[{msg['agent_name']}]: {msg['content']}")
    context = "\n".join(context_lines)

    # Add to local history
    history.append({"role": "user", "content": context})

    # Cap history to prevent context overflow (keep newest 40 entries)
    if len(history) > 40:
        history[:] = history[-40:]

    # Run the agent loop (tools allowed)
    for _ in range(MAX_ROUNDS):
        response = _call_llm(history, system_prompt)
        if response is None or not response.choices:
            _rollback(history)
            return "PASS"

        if response.usage:
            token_counter.add(response.usage.total_tokens)

        msg = response.choices[0].message
        finish_reason = response.choices[0].finish_reason

        assistant_entry: dict = {"role": "assistant", "content": msg.content}
        if msg.tool_calls:
            assistant_entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ]
        history.append(assistant_entry)

        if finish_reason == "stop":
            reply = (msg.content or "").strip()
            if not reply:
                # Tools were used but no text response — should not happen, but
                # return PASS rather than posting an empty message
                return "PASS"
            return "PASS" if reply.upper() == "PASS" else reply

        if finish_reason == "tool_calls":
            for tc in msg.tool_calls:
                inputs = json.loads(tc.function.arguments)
                result = dispatch_tool(tc.function.name, inputs)
                if DEBUG:
                    print(f"  [tool] {tc.function.name} → {result[:80]}")
                history.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
            continue

        _rollback(history)
        return "PASS"

    _rollback(history)
    return "PASS"


def _rollback(history: list) -> None:
    while history and history[-1]["role"] in ("tool", "assistant"):
        history.pop()


def load_system_prompt() -> str:
    text = Path("config/system_prompt.txt").read_text(encoding="utf-8")
    return (
        text
        .replace("{workspace_dir}", str(Path(WORKSPACE_DIR).resolve()))
        .replace("{max_output}", str(MAX_OUTPUT))
        .replace("{agent_name}", AGENT_NAME)
        .replace("{agent_persona}", os.getenv("AGENT_PERSONA", ""))
    )


# ---------------------------------------------------------------------------
# Token counter (shared mutable state — updated from decide())
# ---------------------------------------------------------------------------
class TokenCounter:
    def __init__(self, cap: int) -> None:
        self.total = 0
        self.cap = cap

    def add(self, n: int) -> None:
        self.total += n

    def exceeded(self) -> bool:
        return self.total >= self.cap
