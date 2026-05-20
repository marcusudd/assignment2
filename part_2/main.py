"""
ReAct Agent - Del 2
OpenRouter tool_use with structured output. Own agent loop.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from openai import OpenAI, APIError
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MODEL = os.getenv("MODEL", "anthropic/claude-sonnet-4-6")
WORKSPACE_DIR = os.getenv("WORKSPACE_DIR", "./workspace")
MAX_OUTPUT = int(os.getenv("MAX_OUTPUT", "5000"))
MAX_ROUNDS = int(os.getenv("MAX_ROUNDS", "20"))
DEBUG = os.getenv("DEBUG", "").lower() in ("1", "true")

# ---------------------------------------------------------------------------
# Tool definitions (sent to the API)
# ---------------------------------------------------------------------------
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": (
                f"Run a single bash command in the workspace. "
                f"No chaining with ;, &&, ||, |, or &. "
                f"Output is capped at {MAX_OUTPUT} chars — if truncated, use more targeted commands."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Single bash command to run."}
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                f"Read a file's contents (path relative to workspace). "
                f"Output is capped at {MAX_OUTPUT} chars."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to workspace."}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": (
                "Replace an exact section of a file. old_str must match verbatim (including whitespace). "
                "Returns an error if old_str is not found or matches multiple locations. "
                "Use read_file first to confirm the current content."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to workspace."},
                    "old_str": {"type": "string", "description": "Exact text to find and replace."},
                    "new_str": {"type": "string", "description": "Replacement text."},
                },
                "required": ["path", "old_str", "new_str"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Security guard
# ---------------------------------------------------------------------------
_BLOCKED: list[tuple[str, str]] = [
    # Command chaining
    (r"(?:^|[^|&])(&&|\|\||;|&|\|)(?:[^|&]|$)", "command chaining"),
    # Destructive file operations
    (r"\brm\b.*-[rRfF]", "recursive/force delete"),
    (r"\bdd\b", "dd command"),
    (r"\bmkfs\b", "filesystem format"),
    (r">\s*/dev/", "write to device"),
    # Execution bombs
    (r":\s*\(\s*\)\s*\{", "fork bomb"),
    # Privilege escalation
    (r"\bsudo\b", "sudo"),
    (r"\bsu\b(?:\s|$)", "su"),
    (r"\b(?:pkexec|doas|run0)\b", "privilege escalation"),
    # System commands
    (r"\b(?:shutdown|reboot|halt|poweroff)\b", "system power command"),
    # Remote code execution
    (r"(?:curl|wget)\b.*\|\s*(?:ba)?sh", "remote code execution"),
    (r"(?:curl|wget)\b.*>\s*\S+\.sh\b", "downloading shell scripts"),
    # Reverse shells / exfiltration
    (r"\bnc\b(?:\s|$)|\bnetcat\b", "netcat"),
    # Secrets leakage
    (r"(?:cat|less|head|tail|more)\b.*\.env\b", "reading secrets file"),
    (r"\benv\b(?:\s|$)", "environment variable dump"),
    (r"\bprintenv\b", "environment variable dump"),
    (r"\$\{?(?:OPENROUTER_API_KEY|ANTHROPIC_API_KEY|API_KEY|SECRET|PASSWORD|TOKEN|PRIVATE_KEY)\}?",
     "secret variable expansion"),
    # Home directory access (tilde not caught by absolute path check)
    (r"(?:^|\s|['\"`])~[/\s~]|(?:^|\s|['\"`])~$", "home directory access"),
]


_ALLOWED_ABS_PREFIXES: tuple[str, ...] = (
    "/usr/", "/bin/", "/sbin/", "/lib/", "/opt/", "/tmp/", "/dev/null",
)


def _has_external_path(command: str) -> bool:
    """Returns True if command references an absolute path outside the workspace."""
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
    """Returns a rejection reason if the command is blocked, else None."""
    for pattern, reason in _BLOCKED:
        if re.search(pattern, command, re.IGNORECASE):
            return reason
    if _has_external_path(command):
        return "absolute path outside workspace — use relative paths instead"
    return None


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------
def resolve_path(rel_path: str) -> Path | None:
    """
    Resolve rel_path inside the workspace. Returns None if the path
    would escape the workspace directory (path traversal guard).
    """
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

    print(f"\n🔧 bash: {command}")
    approval = input("   Execute? (y/n): ").strip().lower()
    if approval != "y":
        return "USER DENIED: command was not executed."

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=WORKSPACE_DIR,
        )
        output = result.stdout
        if result.stderr:
            output += f"\nSTDERR: {result.stderr}"
        if result.returncode != 0:
            output += f"\nEXIT CODE: {result.returncode}"
        if not output.strip():
            return "(no output)"
        if len(output) > MAX_OUTPUT:
            return output[:MAX_OUTPUT] + f"\n... (truncated at {MAX_OUTPUT} chars)"
        return output
    except subprocess.TimeoutExpired:
        return "ERROR: command timed out after 30 seconds."
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
            return content[:MAX_OUTPUT] + f"\n... (truncated at {MAX_OUTPUT} chars)"
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
            return "ERROR: old_str not found in file — use read_file to verify the exact content."
        if content.count(old_str) > 1:
            return "ERROR: old_str matches multiple locations — add more context to make it unique."
        updated = content.replace(old_str, new_str, 1)
        target.write_text(updated, encoding="utf-8")
        return f"OK: replaced 1 occurrence in {path}"
    except Exception as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------
def dispatch_tool(name: str, inputs: dict) -> str:
    if name == "bash":
        return tool_bash(inputs["command"])
    if name == "read_file":
        return tool_read_file(inputs["path"])
    if name == "edit_file":
        return tool_edit_file(inputs["path"], inputs["old_str"], inputs["new_str"])
    return f"ERROR: unknown tool '{name}'"


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------
def call_llm(messages: list, system_prompt: str):
    all_messages = [{"role": "system", "content": system_prompt}] + messages
    try:
        return OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY"),
        ).chat.completions.create(
            model=MODEL,
            max_tokens=4096,
            tools=TOOLS,
            messages=all_messages,
        )
    except APIError as e:
        print(f"[API error] {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------
def rollback_incomplete_round(history: list) -> None:
    while history and history[-1]["role"] in ("tool", "assistant"):
        history.pop()


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------
def run_agent(user_message: str, history: list, system_prompt: str) -> str:
    history.append({"role": "user", "content": user_message})

    for round_num in range(MAX_ROUNDS):
        response = call_llm(history, system_prompt)

        if response is None:
            rollback_incomplete_round(history)
            return "API error. Please try again."

        msg = response.choices[0].message
        finish_reason = response.choices[0].finish_reason

        if DEBUG:
            print(f"\n--- round {round_num + 1} | finish={finish_reason} ---")
            print(f"  content: {str(msg.content)[:120]}")
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    print(f"  [tool_call] {tc.function.name}: {tc.function.arguments[:120]}")

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

        if finish_reason == "length":
            rollback_incomplete_round(history)
            return "ERROR: response exceeded max tokens. Try a simpler request."

        if finish_reason == "stop":
            return msg.content or "(no text response)"

        if finish_reason == "tool_calls":
            for tc in msg.tool_calls:
                inputs = json.loads(tc.function.arguments)
                result = dispatch_tool(tc.function.name, inputs)
                preview = result[:200] + ("..." if len(result) > 200 else "")
                print(f"📋 {tc.function.name} → {preview}")
                history.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
            continue

        rollback_incomplete_round(history)
        return f"Unexpected finish reason: {finish_reason}"

    rollback_incomplete_round(history)
    return "Agent reached maximum rounds without a final answer."


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
def validate_startup() -> None:
    if not Path("config/system_prompt.txt").exists():
        raise SystemExit("ERROR: config/system_prompt.txt not found. Run from the part_2 directory.")
    workspace = Path(WORKSPACE_DIR)
    if not workspace.exists():
        workspace.mkdir(parents=True)
        print(f"Created workspace: {workspace.resolve()}")


def load_system_prompt() -> str:
    text = Path("config/system_prompt.txt").read_text(encoding="utf-8")
    return (
        text
        .replace("{workspace_dir}", str(Path(WORKSPACE_DIR).resolve()))
        .replace("{max_output}", str(MAX_OUTPUT))
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    validate_startup()
    system_prompt = load_system_prompt()
    history: list = []

    print("=" * 60)
    print(f"  ReAct Agent - Del 2  [{MODEL}]")
    print("  Type 'quit' to exit, 'clear' to reset history")
    print("=" * 60)

    while True:
        try:
            user_input = input("\n👤 You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nBye!")
            break

        if not user_input:
            continue
        if user_input.lower() == "quit":
            print("Bye!")
            break
        if user_input.lower() == "clear":
            history.clear()
            print("History cleared.")
            continue

        answer = run_agent(user_input, history, system_prompt)
        print(f"\n🤖 Agent: {answer}")


if __name__ == "__main__":
    main()
