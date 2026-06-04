#!/usr/bin/env python3
"""
Official terminal runner — POST /api/run + stream /api/events.

Runs appear in the web GUI (SSE) at the same time as terminal output.
Use this for live demos; keep main.py for offline/direct Rich TUI fallback.

Examples:
  python scripts/run_via_api.py "List all Python files in the workspace"
  python scripts/run_via_api.py --cap 0.35 --preflight "Add /orders …"
  python scripts/run_via_api.py -i
  python scripts/run_via_api.py --no-cloud "List files"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from preflight import run_preflight  # noqa: E402
from api_client import (  # noqa: E402
    DEFAULT_BASE,
    post_run,
    print_run_progress,
    print_run_result,
    stream_run,
)


def _read_task(prompt: str) -> str | None:
    print(prompt, end="", flush=True)
    try:
        return input().strip()
    except (EOFError, KeyboardInterrupt):
        return None


def _print_preflight(base: str) -> bool:
    pf = run_preflight(
        toml_path=ROOT / "config.toml",
        env_path=ROOT / ".env",
        api_base=base,
    )
    print("Demo preflight:")
    for c in pf["checks"]:
        mark = "✓" if c["ok"] else "✗"
        print(f"  {mark} {c['label']}: {c['detail']}")
    print(f"  → {'READY' if pf['ready'] else 'NOT READY (fix critical items)'}")
    print(f"  Cap default: ${pf.get('cap_usd', 0):.2f}")
    print()
    return pf["ready"]


def _run_one(
    client: httpx.Client,
    task: str,
    *,
    cap: float | None,
    allow_local: bool,
    allow_cloud: bool,
    timeout_s: float | None,
    reset_first: bool,
) -> dict:
    if reset_first:
        r = client.post("/api/reset")
        r.raise_for_status()

    run_id = post_run(
        client,
        task,
        cap=cap,
        allow_local=allow_local,
        allow_cloud=allow_cloud,
    )
    print(f"Started run_id={run_id} — GUI updates at {client.base_url}")
    last_phase = None

    def on_payload(p: dict) -> None:
        nonlocal last_phase
        last_phase = print_run_progress(p, last_phase=last_phase)

    final = stream_run(client, run_id, on_payload=on_payload, timeout_s=timeout_s)
    print_run_result(final)
    return final


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Bifrost via API (visible in web GUI + terminal)",
    )
    parser.add_argument("task", nargs="*", help="Task text (omit for -i REPL)")
    parser.add_argument("--base", default=DEFAULT_BASE, help="API base URL")
    parser.add_argument("--cap", type=float, help="Cost cap USD for this run")
    parser.add_argument("--timeout", type=float, default=900, help="Max seconds per run")
    parser.add_argument("--reset", action="store_true", help="Reset workspace before run")
    parser.add_argument("--preflight", action="store_true", help="Print readiness checks and exit 1 if not ready")
    parser.add_argument("--no-local", action="store_true", help="Disable Midgard (local) for this run")
    parser.add_argument("--no-cloud", action="store_true", help="Disable Asgard (cloud) for this run")
    parser.add_argument("-i", "--interactive", action="store_true", help="REPL: multiple tasks via API")
    args = parser.parse_args()

    if args.preflight:
        ok = _print_preflight(args.base)
        sys.exit(0 if ok else 1)

    allow_local = not args.no_local
    allow_cloud = not args.no_cloud
    if not allow_local and not allow_cloud:
        print("Enable at least one realm (--no-local / --no-cloud).", file=sys.stderr)
        sys.exit(2)

    with httpx.Client(base_url=args.base.rstrip("/"), timeout=30.0) as client:
        h = client.get("/api/health")
        h.raise_for_status()
        print(f"API OK — open {args.base} to watch the same run in the GUI.\n")

        if args.interactive or not args.task:
            print("Commands: cap <usd> · reset · compact · local on|off · cloud on|off · exit")
            cap = args.cap
            while True:
                task = _read_task(f"\n🌉 [cap ${cap or 'default'}] Task: ")
                if task is None:
                    break
                if not task:
                    continue
                low = task.lower()
                if low in ("exit", "quit", "q"):
                    break
                if low == "reset":
                    client.post("/api/reset").raise_for_status()
                    print("Workspace reset.")
                    continue
                if low.startswith("cap "):
                    try:
                        cap = float(low.split()[1])
                        print(f"Cap set to ${cap:.2f} for next run.")
                    except (IndexError, ValueError):
                        print("Usage: cap 0.35")
                    continue
                if low == "compact":
                    try:
                        client.post("/api/compact").raise_for_status()
                        print("Compaction requested.")
                    except httpx.HTTPStatusError as e:
                        print(e.response.json().get("detail", e))
                    continue
                if low in ("local on", "local off"):
                    allow_local = low.endswith("on")
                    print(f"Midgard {'on' if allow_local else 'off'} for next run.")
                    continue
                if low in ("cloud on", "cloud off"):
                    allow_cloud = low.endswith("on")
                    print(f"Asgard {'on' if allow_cloud else 'off'} for next run.")
                    continue
                _run_one(
                    client,
                    task,
                    cap=cap,
                    allow_local=allow_local,
                    allow_cloud=allow_cloud,
                    timeout_s=args.timeout,
                    reset_first=False,
                )
        else:
            _run_one(
                client,
                " ".join(args.task),
                cap=args.cap,
                allow_local=allow_local,
                allow_cloud=allow_cloud,
                timeout_s=args.timeout,
                reset_first=args.reset,
            )


if __name__ == "__main__":
    main()
