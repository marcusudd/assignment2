"""
ReAct Agent - Del 1
A simple agent with homemade XML-based function calling.
No frameworks, no built-in tool use - just raw text parsing.
"""

import os
import re
import subprocess
import sys
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MODEL = os.getenv("MODEL") or "claude-sonnet-4-6"
WORKSPACE_DIR = os.getenv("WORKSPACE_DIR", "./workspace")
DEBUG = os.getenv("DEBUG", "").lower() in ("1", "true")
MAX_TOKENS = 4096
MAX_ROUNDS = 10

# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------
def validate_startup() -> None:
    if not os.path.exists("system_prompt.txt"):
        raise SystemExit("ERROR: system_prompt.txt not found. Run from the project directory.")
    if not os.path.exists(WORKSPACE_DIR):
        os.makedirs(WORKSPACE_DIR)
        print(f"Created workspace directory: {WORKSPACE_DIR}")

# ---------------------------------------------------------------------------
# Load system prompt from file
# ---------------------------------------------------------------------------
def load_system_prompt(path: str = "system_prompt.txt") -> str:
    with open(path, "r") as f:
        text = f.read()
    workspace_abs = os.path.abspath(WORKSPACE_DIR)
    return text.replace("{workspace_dir}", workspace_abs)

# ---------------------------------------------------------------------------
# XML Parsing - Homemade function calling
# ---------------------------------------------------------------------------
def parse_thought(text: str) -> str | None:
    match = re.search(r"<thought>(.*?)</thought>", text, re.DOTALL)
    return match.group(1).strip() if match else None

def parse_action(text: str) -> dict | None:
    action_match = re.search(r"<action>(.*?)</action>", text, re.DOTALL)
    if not action_match:
        return None
    action_block = action_match.group(1)
    tool_match = re.search(r"<tool>(.*?)</tool>", action_block, re.DOTALL)
    input_match = re.search(r"<input>(.*?)</input>", action_block, re.DOTALL)
    if tool_match and input_match:
        return {
            "tool": tool_match.group(1).strip(),
            "input": input_match.group(1).strip(),
        }
    return None

def parse_answer(text: str) -> str | None:
    match = re.search(r"<answer>(.*?)</answer>", text, re.DOTALL)
    return match.group(1).strip() if match else None

# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------
def call_llm(messages: list, system_prompt: str) -> tuple[str, str]:
    """
    Returns (text, stop_reason) where stop_reason is one of:
      "action_stop" — stopped at </action>, caller should append it back
      "end_turn"    — natural stop
      "max_tokens"  — hit token limit
      "error"       — API error, text contains the message
    """
    from anthropic import Anthropic, APIError
    try:
        response = Anthropic().messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=messages,
            stop_sequences=["</action>"],
        )
    except APIError as e:
        return e.message, "error"
    text = response.content[0].text if response.content else ""
    if response.stop_reason == "stop_sequence":
        return text, "action_stop"
    if response.stop_reason == "max_tokens":
        return text, "max_tokens"
    return text, "end_turn"

# ---------------------------------------------------------------------------
# Command execution with safety check
# ---------------------------------------------------------------------------
_CHAIN_OPERATORS = re.compile(r"(?:^|[^|&])(&&|\|\||;|&|\|)(?:[^|&]|$)")

def execute_command(command: str) -> str:
    if _CHAIN_OPERATORS.search(command):
        return "RULE VIOLATION: Command contains chaining operators (&&, ||, ;, |, &). Use one command per action."
    print(f"\n🔧 Agent wants to run: {command}")
    approval = input("   Execute? (y/n): ").strip().lower()
    if approval != "y":
        return "USER DENIED: Command was not executed."
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=WORKSPACE_DIR,
        )
        output = result.stdout.encode("utf-8", errors="replace").decode("utf-8")
        if result.stderr:
            output += f"\nSTDERR: {result.stderr.encode('utf-8', errors='replace').decode('utf-8')}"
        if result.returncode != 0:
            output += f"\nEXIT CODE: {result.returncode}"
        if len(output) > 5000:
            output = output[:5000] + "\n... (output truncated)"
        return output if output.strip() else "(no output)"
    except subprocess.TimeoutExpired:
        return "ERROR: Command timed out after 30 seconds."
    except Exception as e:
        return f"ERROR: {e}"

# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------
def run_agent(user_message: str, conversation_history: list, system_prompt: str) -> str:
    conversation_history.append({"role": "user", "content": user_message})

    for _round in range(MAX_ROUNDS):
        text, stop_reason = call_llm(conversation_history, system_prompt)

        if stop_reason in ("error", "max_tokens"):
            # Roll back any trailing user messages so history stays alternating.
            while conversation_history and conversation_history[-1]["role"] == "user":
                conversation_history.pop()
            if stop_reason == "error":
                return f"API error: {text}"
            return "ERROR: Response exceeded max tokens. Try a simpler request."

        assistant_text = text + "</action>" if stop_reason == "action_stop" else text

        if DEBUG:
            print(f"\n--- RAW RESPONSE (round {_round + 1}) ---\n{assistant_text}\n--- END RAW ---")
        conversation_history.append({"role": "assistant", "content": assistant_text})

        thought = parse_thought(assistant_text)
        if thought:
            print(f"\n💭 Thought: {thought}")

        # Check for action FIRST — if both <action> and <answer> appear in the
        # same response, the answer is premature and must be discarded.
        action = parse_action(assistant_text)
        if action:
            if action["tool"] == "bash":
                result = execute_command(action["input"])
                print(f"📋 Result: {result[:200]}{'...' if len(result) > 200 else ''}")
                conversation_history.append({"role": "user", "content": f"<observation>{result}</observation>"})
            else:
                error_msg = f"Unknown tool: {action['tool']}. Only 'bash' is available."
                conversation_history.append({"role": "user", "content": f"<observation>{error_msg}</observation>"})
            continue

        answer = parse_answer(assistant_text)
        if answer:
            return answer

        # Model didn't follow the format — return raw response
        print("[WARN] Model response did not match expected format", file=sys.stderr)
        return assistant_text

    # Roll back trailing user messages (observations) so history stays alternating.
    while conversation_history and conversation_history[-1]["role"] == "user":
        conversation_history.pop()
    return "Agent reached maximum rounds without a final answer."

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    validate_startup()
    system_prompt = load_system_prompt()
    conversation_history = []

    print("=" * 60)
    print(f"  ReAct Agent - Del 1  [{MODEL}]")
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
            conversation_history.clear()
            print("History cleared.")
            continue

        answer = run_agent(user_input, conversation_history, system_prompt)
        print(f"\n🤖 Agent: {answer}")

if __name__ == "__main__":
    main()
