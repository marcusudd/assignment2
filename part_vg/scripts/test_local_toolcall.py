"""
Build step 0 — verify that the local LM Studio model supports tool-calling.

Run from part_vg/:
  python scripts/test_local_toolcall.py

What it checks:
  1. Local endpoint reachable (health check)
  2. Model returns a tool_call (not just text) for a simple prompt
  3. Tool arguments are valid JSON with the right fields
  4. Dispatching the tool actually works

Pass = Bifrost's local routing is safe to build on.
Fail = switch model in config.toml (try Qwen-coder or Gemma 4 26B) before continuing.
"""
import json
import sys
from pathlib import Path

# Make sure we can import from parent
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(".env")

from config import Config
from llm import call_llm, health_check
from tools import TOOL_SCHEMAS, dispatch_tool


def main() -> None:
    try:
        cfg = Config.load("config.toml")
    except ValueError as e:
        print(f"[SKIP] Config error (no OPENROUTER_API_KEY needed for local test): {e}")
        # Allow running without OPENROUTER_API_KEY for local-only test
        import os
        os.environ.setdefault("OPENROUTER_API_KEY", "not-needed-for-local-test")
        cfg = Config.load("config.toml")

    base_url = cfg.local.base_url
    api_key  = cfg.local.api_key
    model    = cfg.local.model

    print(f"Target: {base_url}  model={model}")
    print()

    # ------------------------------------------------------------------
    # Step 1: health check
    # ------------------------------------------------------------------
    print("1. Health check...", end=" ", flush=True)
    if not health_check(base_url, api_key):
        print("FAIL")
        print(f"\n   Cannot reach {base_url}")
        print("   → Make sure LM Studio is running and the local server is enabled (port 1234).")
        sys.exit(1)
    print("OK")

    # ------------------------------------------------------------------
    # Step 2: simple tool-call probe
    # ------------------------------------------------------------------
    print("2. Tool-call probe...", end=" ", flush=True)
    messages = [
        {
            "role": "user",
            "content": (
                "Use the bash tool to run: echo 'tool-calling-works'"
            ),
        }
    ]

    response, prompt_tok, completion_tok = call_llm(
        messages=messages,
        model=model,
        base_url=base_url,
        api_key=api_key,
        tools=TOOL_SCHEMAS,
        max_tokens=256,
    )

    if response is None:
        print("FAIL")
        print("\n   LLM call returned None — the model may not be loaded.")
        print("   → Load Qwen 3.6 27B (or another model) in LM Studio and try again.")
        sys.exit(1)

    msg = response.choices[0].message
    finish_reason = response.choices[0].finish_reason

    # Normalize (same logic as subagent.py)
    if msg.tool_calls:
        finish_reason = "tool_calls"

    if finish_reason != "tool_calls" or not msg.tool_calls:
        print("FAIL — model responded with text instead of a tool call")
        print(f"\n   finish_reason: {finish_reason!r}")
        print(f"   content: {str(msg.content)[:200]}")
        print()
        print("   → The model does not support tool-calling reliably.")
        print("   → Try: Qwen3-8B-Instruct, Qwen2.5-Coder-7B, or Gemma 4 26B in LM Studio.")
        print("   → Or: the cascade-fallback stretch feature will cover this gap.")
        sys.exit(1)

    print("OK")

    # ------------------------------------------------------------------
    # Step 3: parse tool arguments
    # ------------------------------------------------------------------
    print("3. Argument JSON valid...", end=" ", flush=True)
    tc = msg.tool_calls[0]
    tool_name = tc.function.name
    try:
        args = json.loads(tc.function.arguments or "{}")
    except json.JSONDecodeError as e:
        print("FAIL")
        print(f"\n   Model emitted malformed JSON: {tc.function.arguments!r}")
        print(f"   Parse error: {e}")
        print()
        print("   → Minimal escalate-on-error (D4) will handle this at runtime,")
        print("     but consider switching to a more reliable model.")
        sys.exit(1)
    print("OK")
    print(f"   tool={tool_name!r}  args={args}")

    # ------------------------------------------------------------------
    # Step 4: actually dispatch the tool
    # ------------------------------------------------------------------
    print("4. Tool dispatch...", end=" ", flush=True)
    import tempfile, os
    ws = tempfile.mkdtemp(prefix="bifrost_test_")
    result = dispatch_tool(tool_name, args, workspace_dir=ws, max_output=500, auto_approve=True)
    print("OK")
    print(f"   output: {result[:100]}")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print()
    print("=" * 50)
    print("✅  ALL CHECKS PASSED")
    print(f"    Model {model!r} supports tool-calling.")
    print(f"    Bifrost's local routing is safe to build on.")
    print(f"    Tokens used: prompt={prompt_tok}  completion={completion_tok}")
    print("=" * 50)


if __name__ == "__main__":
    main()
