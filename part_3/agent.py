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

MODEL = os.getenv("MODEL", "google/gemini-2.5-flash")
WORKSPACE_DIR = os.getenv("WORKSPACE_DIR", "./workspace")
MAX_OUTPUT = int(os.getenv("MAX_OUTPUT", "5000"))
MAX_ROUNDS = int(os.getenv("MAX_ROUNDS", "10"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "2048"))
DEBUG = os.getenv("DEBUG", "").lower() in ("1", "true")
AUTO_APPROVE = os.getenv("AUTO_APPROVE", "false").lower() in ("1", "true")
AGENT_NAME = os.getenv("AGENT_NAME", "macmini1")

_last_turn_written_files: list[str] = []


def get_last_turn_written_files() -> list[str]:
    """Paths written via bash/edit_file in the most recent decide() call."""
    return list(_last_turn_written_files)

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

# Files that the active operator directive requires — main.py updates this
# before each decide() call so the security guard can block destructive
# operations against them (rm / find -delete) even when an agent's prior
# tool chain "looks reasonable".
_PROTECTED_FILES: set[str] = set()


def set_protected_files(names) -> None:
    """Replace the set of files protected from rm / find -delete in this process."""
    global _PROTECTED_FILES
    _PROTECTED_FILES = {n for n in names if n and n != ".gitkeep"}


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
    # Protect operator-spec files from destructive ops even without -rf flags.
    # Agents have been observed running `rm app.py` or `find . -delete` and
    # wiping a peer's completed file from the same operator directive.
    if _PROTECTED_FILES:
        if re.search(r"\bfind\b.*-delete\b", command, re.IGNORECASE):
            return "find -delete with active operator spec (may remove required files)"
        if re.search(r"\brm\b", command, re.IGNORECASE):
            for fname in _PROTECTED_FILES:
                if re.search(rf"(?:^|[\s/]){re.escape(fname)}\b", command):
                    return f"removing protected file '{fname}' (active operator spec)"
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
    if target.name == ".env" or target.name.endswith(".env"):
        return "ERROR: reading .env files is not allowed."
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
    try:
        if name == "bash":
            return tool_bash(inputs["command"])
        if name == "read_file":
            return tool_read_file(inputs["path"])
        if name == "edit_file":
            return tool_edit_file(inputs["path"], inputs["old_str"], inputs["new_str"])
        return f"ERROR: unknown tool '{name}'"
    except KeyError as e:
        return f"ERROR: tool '{name}' called with missing argument {e}. Required args: bash needs 'command', read_file needs 'path', edit_file needs 'path'+'old_str'+'new_str'."
    except Exception as e:
        return f"ERROR: tool '{name}' failed: {e}"


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
            max_tokens=MAX_TOKENS,
            tools=TOOLS,
            messages=all_messages,
        )
    except APIError as e:
        print(f"[LLM API error] {e}", file=sys.stderr)
        return None
    except Exception as e:
        # Catch transient network errors, TLS failures, malformed JSON from provider,
        # etc. Decide() handles None gracefully (rollback + PASS).
        print(f"[LLM unexpected error: {type(e).__name__}] {e}", file=sys.stderr)
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
    global _last_turn_written_files
    _last_turn_written_files = []

    # Self-echo guard: defence-in-depth in case caller passes unfiltered messages
    if len(new_messages) >= 3 and all(m["agent_name"] == own_name for m in new_messages[-3:]):
        return "PASS"

    # Build conversation context from recent hub messages
    context_lines = []
    for msg in new_messages[-20:]:
        context_lines.append(f"[{msg['agent_name']}]: {msg['content']}")
    context = "\n".join(context_lines)

    # Inject agent registry so LLM uses real names in @mentions, not literal "@agent-name"
    agent_names = sorted({m["agent_name"] for m in new_messages
                          if m["agent_name"] != own_name})
    if agent_names:
        registry = "Other agents currently in chat: " + ", ".join(f"@{n}" for n in agent_names)
        context = registry + "\n\n" + context

    # Add to local history
    history.append({"role": "user", "content": context})

    # Cap history to prevent context overflow (keep newest 24 entries ≈ 4 response cycles)
    if len(history) > 24:
        history[:] = history[-24:]

    # Run the agent loop (tools allowed)
    tools_used = False
    report_forced = False
    this_turn_tools: list[str] = []  # Track for auto-fallback if LLM refuses to report
    this_turn_files: list[str] = []  # Files written this turn — pasted in auto-fallback

    def _finish(reply: str) -> str:
        _last_turn_written_files[:] = this_turn_files
        return reply

    for _ in range(MAX_ROUNDS):
        response = _call_llm(history, system_prompt)
        if response is None or not response.choices:
            _rollback(history)
            return _finish("PASS")

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

        # Normalize finish_reason across providers (Anthropic via OpenRouter may return
        # "end_turn", "tool_use", "max_tokens" etc. instead of OpenAI-style values).
        # Trust the actual message shape: tool_calls present → tool round; otherwise → stop.
        if msg.tool_calls:
            finish_reason = "tool_calls"
        elif finish_reason not in ("stop", "tool_calls"):
            finish_reason = "stop"

        if finish_reason == "stop":
            reply = (msg.content or "").strip()
            if not reply:
                # Empty reply: if tools were used, generate fallback instead of going silent
                if tools_used and this_turn_tools:
                    print("[decide] empty reply after tools — using auto-fallback", file=sys.stderr)
                    return _finish(_build_autosummary(this_turn_tools, this_turn_files))
                return _finish("PASS")
            # If LLM used tools but said PASS, force one retry demanding a report
            if reply.upper() == "PASS" and tools_used and not report_forced:
                report_forced = True
                print(f"[decide] tools used but LLM said PASS — forcing report retry", file=sys.stderr)
                history.append({
                    "role": "user",
                    "content": (
                        "You called tools this turn — that means you did work or "
                        "investigated the workspace. You MUST report what you did or "
                        "found in 2-3 sentences. Do not say PASS. Write your report now."
                    ),
                })
                continue
            # Retry failed; if tools were used, generate auto-fallback so chat isn't silent
            if reply.upper() == "PASS" and tools_used and this_turn_tools:
                print("[decide] LLM refused report after tools — using auto-fallback", file=sys.stderr)
                return _finish(_build_autosummary(this_turn_tools, this_turn_files))
            return _finish("PASS" if reply.upper() == "PASS" else reply)

        if finish_reason == "tool_calls":
            tools_used = True
            for tc in msg.tool_calls:
                try:
                    inputs = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    result = "ERROR: invalid tool arguments JSON from model."
                    history.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    })
                    continue
                result = dispatch_tool(tc.function.name, inputs)
                if DEBUG:
                    print(f"  [tool] {tc.function.name} → {result[:80]}")
                # Track for auto-fallback
                tname = tc.function.name
                if tname == "bash":
                    cmd = inputs.get("command", "")
                    this_turn_tools.append(f"ran `{cmd[:60]}`")
                    written = _extract_written_file(cmd)
                    if written:
                        this_turn_files.append(written)
                elif tname == "edit_file":
                    path = inputs.get("path", "?")
                    this_turn_tools.append(f"edited `{path}`")
                    if path and path != "?":
                        this_turn_files.append(path)
                elif tname == "read_file":
                    this_turn_tools.append(f"read `{inputs.get('path', '?')}`")
                # Store trimmed result in history — full output already seen by LLM this round.
                history_content = result if len(result) <= 300 else result[:297] + "…"
                history.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": history_content,
                })
            continue

        _rollback(history)
        return _finish("PASS")

    # MAX_ROUNDS exhausted without "stop" — if tools were used, generate fallback report
    if tools_used and this_turn_tools:
        print("[decide] MAX_ROUNDS reached with tools — using auto-fallback", file=sys.stderr)
        return _finish(
            _build_autosummary(this_turn_tools, this_turn_files, suffix=" (max rounds reached)"),
        )
    _rollback(history)
    return _finish("PASS")


def _rollback(history: list) -> None:
    while history and history[-1]["role"] in ("tool", "assistant"):
        history.pop()


_WRITE_FILE_RE = re.compile(
    r">>?\s*['\"]?([\w./-]+\.[\w]+)['\"]?",
)

_LANG_BY_EXT = {
    "py": "python", "js": "javascript", "ts": "typescript", "jsx": "jsx",
    "tsx": "tsx", "sh": "bash", "md": "markdown", "sql": "sql", "json": "json",
    "yaml": "yaml", "yml": "yaml", "html": "html", "css": "css", "toml": "toml",
}


def _extract_written_file(command: str) -> str | None:
    """Return filename from a heredoc/redirect bash command, if any."""
    if not command:
        return None
    m = _WRITE_FILE_RE.search(command)
    return m.group(1) if m else None


def _build_autosummary(
    tools: list[str], files: list[str], suffix: str = "",
) -> str:
    """Compose the [auto-summary] fallback message, pasting last-written file if small."""
    actions = tools[-4:]
    base = f"[auto-summary] Actions this turn: {'; '.join(actions)}{suffix}."
    if not files:
        return base
    seen: set[str] = set()
    ordered: list[str] = []
    for f in files:
        if f not in seen:
            seen.add(f)
            ordered.append(f)
    target = ordered[-1]
    try:
        p = Path(WORKSPACE_DIR) / target
        if not p.is_file():
            return base
        content = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return base
    if len(content) > 3000:
        return base + f"\n\nFile `{target}` ({len(content)} chars — full file on workspace)."
    ext = target.rsplit(".", 1)[-1].lower() if "." in target else ""
    lang = _LANG_BY_EXT.get(ext, "")
    return base + f"\n\nFile `{target}`:\n```{lang}\n{content}\n```"




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

    def soft_exceeded(self) -> bool:
        return self.total >= self.cap * 0.75

    def hard_exceeded(self) -> bool:
        return self.total >= self.cap * 0.90
