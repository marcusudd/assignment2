"""
Build step 0 — verify local LM Studio models support tool-calling.

Run from part_vg/:
  PYTHONPATH=. python scripts/test_local_toolcall.py

Tests LOCAL_MODEL always, and LOCAL_MODEL_2 when set in .env.
Pass = safe to demo dual-local + Bifrost local routing.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(".env")

from config import Config
from llm import call_llm, health_check
from tools import TOOL_SCHEMAS, dispatch_tool


def _load_config() -> Config:
    try:
        return Config.load("config.toml")
    except ValueError:
        os.environ.setdefault("OPENROUTER_API_KEY", "not-needed-for-local-test")
        return Config.load("config.toml")


def _models_to_test(cfg: Config) -> list[tuple[str, str]]:
    """Return (label, model_id) for each local slot to probe."""
    out: list[tuple[str, str]] = [(cfg.locals[0].name, cfg.locals[0].model)]
    if len(cfg.locals) > 1:
        out.append((cfg.locals[1].name, cfg.locals[1].model))
    return out


def _probe_model(base_url: str, api_key: str, model: str) -> None:
    messages = [
        {
            "role": "user",
            "content": "Use the bash tool to run: echo 'tool-calling-works'",
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
        raise RuntimeError("LLM call returned None — model may not be loaded")

    msg = response.choices[0].message
    finish_reason = response.choices[0].finish_reason
    if msg.tool_calls:
        finish_reason = "tool_calls"

    if finish_reason != "tool_calls" or not msg.tool_calls:
        raise RuntimeError(
            f"no tool_call (finish_reason={finish_reason!r}, "
            f"content={str(msg.content)[:120]!r})"
        )

    tc = msg.tool_calls[0]
    args = json.loads(tc.function.arguments or "{}")
    ws = tempfile.mkdtemp(prefix="bifrost_test_")
    result = dispatch_tool(
        tc.function.name, args, workspace_dir=ws, max_output=500, auto_approve=True
    )
    if "ERROR" in result[:20]:
        raise RuntimeError(f"dispatch failed: {result[:200]}")

    print(f"      tokens: prompt={prompt_tok} completion={completion_tok}")
    print(f"      tool={tc.function.name!r}  output={result[:80]!r}")


def main() -> None:
    cfg = _load_config()
    base_url = cfg.locals[0].base_url
    api_key = cfg.locals[0].api_key
    models = _models_to_test(cfg)

    print(f"Endpoint: {base_url}")
    print(f"Models to test: {', '.join(m for _, m in models)}")
    print()

    print("1. Health check...", end=" ", flush=True)
    if not health_check(base_url, api_key):
        print("FAIL")
        print(f"\n   Cannot reach {base_url}")
        print("   → Start LM Studio and enable the local server (port 1234).")
        sys.exit(1)
    print("OK")
    print()

    failed = False
    for label, model in models:
        print(f"── {label}: {model!r} ──")
        print("   Tool-call probe...", end=" ", flush=True)
        try:
            _probe_model(base_url, api_key, model)
            print("OK")
        except Exception as e:
            print("FAIL")
            print(f"   {e}")
            if "gemma-4-e4b" in model:
                print("   → Load gemma-4-e4b in LM Studio (dual-local demo slot).")
            else:
                print("   → Load the model in LM Studio or pick another in .env.")
            failed = True
        print()

    print("=" * 50)
    if failed:
        print("❌  SOME CHECKS FAILED — fix before live demo")
        sys.exit(1)
    print("✅  ALL LOCAL MODELS PASSED")
    print("    Bifrost local routing is ready.")
    if len(models) > 1:
        print("    Dual-local: two models verified for parallel local workers.")
    print("=" * 50)


if __name__ == "__main__":
    main()
