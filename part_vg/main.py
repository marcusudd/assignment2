"""
Bifrost — entry point (direct Rich TUI, offline fallback).

For runs visible in the web GUI, use: python scripts/run_via_api.py

Usage:
  python main.py "Add /orders endpoint with business logic"
  python main.py --cap 0.05 "List all Python files in the workspace"
  python main.py --interactive          # REPL: run tasks one after another
  python main.py --no-local "..."       # Midgard off (cloud only)
  python main.py --no-cloud "..."       # Asgard off (local only)
  python main.py --no-verbose "..."     # Simple UI without per-worker log

All options can also be set via config.toml / .env.
"""
import argparse
import select
import subprocess
import sys
import time
from pathlib import Path

from session_log import Tee, open_session_log, write_session_summary
from workspace_diff import diff_workspace, snapshot_workspace


def _load_system_prompt(config) -> str:
    here = Path(__file__).parent
    path = here / "config" / "system_prompt.txt"
    text = path.read_text(encoding="utf-8")
    return (
        text
        .replace("{workspace_dir}", str(Path(config.workspace_dir).resolve()))
        .replace("{max_output}", str(config.max_output))
        .replace("{python_cmd}", "python3")
    )


def _reset_workspace() -> None:
    script = Path(__file__).parent / "scripts" / "clear_workspace.sh"
    subprocess.run(["bash", str(script)], check=False)


def _api_compact(base: str = "http://127.0.0.1:8000") -> str | None:
    """Request compaction on the active API run; None if server unavailable."""
    try:
        import httpx

        r = httpx.post(f"{base.rstrip('/')}/api/compact", timeout=3.0)
        if r.status_code == 200:
            return "Compaction requested (API run)."
        detail = r.json().get("detail", r.text)
        return f"Compact failed: {detail}"
    except Exception as e:
        return None


def _read_task_input(prompt: str) -> str | None:
    """Read a (possibly multi-line / pasted) task from the user.

    When a user pastes several lines, the terminal sends them as one burst —
    ``input()`` only returns the first line, leaving the rest in the stdin
    buffer where it leaks into the *next* input() call. We fix this by reading
    the first line normally, then draining any additional lines that are
    *already* buffered (no blocking). For manual single-line input this
    behaves exactly like input().
    """
    print(prompt, end="", flush=True)
    try:
        first = input()
    except (EOFError, KeyboardInterrupt):
        return None
    lines = [first]
    # Drain lines from a paste. 1 s timeout: terminals batch paste chunks up to
    # ~500 ms apart; going below that reliably splits multi-line pastes.
    # Single-line input is unaffected — the 1 s wait only fires once, after the
    # user presses Enter, which is indistinguishable from normal shell latency.
    while True:
        ready, _, _ = select.select([sys.stdin], [], [], 1.0)
        if not ready:
            break
        try:
            lines.append(input())
        except (EOFError, KeyboardInterrupt):
            break
    return " ".join(line.strip() for line in lines if line.strip())


def _run_task(
    task: str,
    config,
    local_backends,
    cloud_backend,
    system_prompt: str,
    verbose: bool,
    *,
    allow_local: bool = True,
    allow_cloud: bool = True,
) -> None:
    from cost import CostTracker
    from orchestrator import Orchestrator
    from state import StateRegistry
    from ui import Dashboard

    log_path, log_fh = open_session_log(task)
    real_stderr = sys.stderr
    sys.stderr = Tee(real_stderr, log_fh)  # type: ignore[assignment]

    try:
        prices_path = Path(__file__).parent / "model_prices.json"
        cost_tracker = CostTracker(
            cap_usd=config.cost_cap_usd,
            warning_threshold=config.cost_warning_threshold,
            prices_path=str(prices_path),
        )
        registry = StateRegistry()

        dashboard = Dashboard(
            task=task,
            registry=registry,
            cost_tracker=cost_tracker,
            comparison_models=config.comparison_models,
            verbose=verbose,
        )

        orch = Orchestrator(
            config=config,
            local_backends=local_backends,
            cloud_backend=cloud_backend,
            cost_tracker=cost_tracker,
            registry=registry,
            worker_system_prompt=system_prompt,
            allow_local=allow_local,
            allow_cloud=allow_cloud,
        )

        before_files = snapshot_workspace(config.workspace_dir)

        dashboard.start()
        try:
            result = orch.run(task)
            dashboard.set_routing_summary(orch.routing_summary)
            time.sleep(0.5)
        except KeyboardInterrupt:
            result = "Interrupted."
        finally:
            dashboard.stop()

        print("\n" + "=" * 60)
        print("Result:")
        print(result)
        print("=" * 60)

        created, modified = diff_workspace(
            before_files, snapshot_workspace(config.workspace_dir)
        )
        print("\nBuilt:")
        if not created and not modified:
            print("  (no file changes)")
        for f in created:
            print(f"  + {f}")
        for f in modified:
            print(f"  ~ {f}")

        snap = cost_tracker.snapshot()
        print(f"\nCost: ${snap['total_usd']:.4f} / ${snap['cap_usd']:.2f}")

        cf = cost_tracker.counterfactual(config.comparison_models)
        if cf:
            print("\nAll-cloud comparison:")
            for model, cost in sorted(cf.items(), key=lambda x: -x[1]):
                saved = cost - snap["total_usd"]
                print(f"  {model:<40} ${cost:.4f}  (saved ${saved:.4f})")

        write_session_summary(
            log_fh,
            task=task,
            result=result,
            snap=snap,
            registry=registry,
            routing=orch.routing_summary,
            built=(created, modified),
        )

    finally:
        sys.stderr = real_stderr
        log_fh.close()
        print(f"\n[log] {log_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="bifrost",
        description="Local-first hybrid coding agent with cost transparency",
    )
    parser.add_argument("task", nargs="*", help="Task description (omit for --interactive)")
    parser.add_argument("--cap", type=float, help="Override cost cap (USD)")
    parser.add_argument("--config", default="config.toml", help="Config file path")
    parser.add_argument("--no-verbose", action="store_true", help="Simple UI")
    parser.add_argument("--no-local", action="store_true", help="Disable Midgard (local workers)")
    parser.add_argument("--no-cloud", action="store_true", help="Disable Asgard (cloud workers)")
    parser.add_argument(
        "--api-base",
        default="http://127.0.0.1:8000",
        help="Base URL for REPL 'compact' when server is running (default :8000)",
    )
    parser.add_argument("--interactive", "-i", action="store_true",
                        help="REPL mode: run tasks one after another, workspace persists")
    args = parser.parse_args()

    if args.no_local and args.no_cloud:
        print("Enable at least one realm (omit --no-local and --no-cloud).", file=sys.stderr)
        sys.exit(2)
    allow_local = not args.no_local
    allow_cloud = not args.no_cloud

    from config import Config
    config = Config.load(toml_path=args.config)
    if args.cap is not None:
        config.cost_cap_usd = args.cap

    Path(config.workspace_dir).mkdir(parents=True, exist_ok=True)

    from backends import resolve
    local_backends, cloud_backend = resolve(config)

    system_prompt = _load_system_prompt(config)
    verbose = not args.no_verbose

    if args.interactive or not args.task:
        # ----------------------------------------------------------------
        # REPL mode
        # ----------------------------------------------------------------
        print("\n" + "─" * 60)
        print("  Bifrost — interactive mode")
        print("  Commands: cap <usd> · clear · compact · local on|off · cloud on|off · exit")
        print("  compact → POST /api/compact when server is up; else use scripts/run_via_api.py")
        print("  Multi-line / pasted prompts are accepted.")
        print(f"  Cap ${config.cost_cap_usd:.2f} is applied PER task (not session).")
        print(f"  Realms: Midgard={'on' if allow_local else 'off'} · Asgard={'on' if allow_cloud else 'off'}")
        print("─" * 60)
        while True:
            task = _read_task_input(f"\n🌉 [cap ${config.cost_cap_usd:.2f}] Task: ")
            if task is None:
                print("\nBye!")
                break
            if not task:
                continue
            if task.lower() in ("exit", "quit", "q"):
                print("Bye!")
                break
            if task.lower() in ("clear", "reset"):
                _reset_workspace()
                print("Workspace cleared.")
                continue
            if task.lower() == "compact":
                msg = _api_compact(args.api_base)
                if msg:
                    print(msg)
                else:
                    print(
                        "No API server — start uvicorn server:app or use "
                        "scripts/run_via_api.py -i for compact during GUI runs."
                    )
                continue
            if task.lower() in ("local on", "local off"):
                allow_local = task.lower().endswith("on")
                print(f"Midgard {'on' if allow_local else 'off'} for next task.")
                continue
            if task.lower() in ("cloud on", "cloud off"):
                allow_cloud = task.lower().endswith("on")
                print(f"Asgard {'on' if allow_cloud else 'off'} for next task.")
                continue
            if task.lower() == "cap" or task.lower().startswith("cap "):
                parts = task.split()
                if len(parts) == 2:
                    try:
                        config.cost_cap_usd = float(parts[1])
                        print(f"Cost cap set to ${config.cost_cap_usd:.2f} (applies to the next task).")
                    except ValueError:
                        print("Usage: cap <usd>, e.g. cap 0.50")
                else:
                    print(f"Current cap: ${config.cost_cap_usd:.2f}. Usage: cap <usd>")
                continue

            # Re-resolve backends so LM Studio coming online mid-session is detected.
            local_backends, cloud_backend = resolve(config)
            _run_task(
                task,
                config,
                local_backends,
                cloud_backend,
                system_prompt,
                verbose,
                allow_local=allow_local,
                allow_cloud=allow_cloud,
            )
            print()   # blank line before next prompt
    else:
        # ----------------------------------------------------------------
        # Single-shot mode (original behaviour)
        # ----------------------------------------------------------------
        _run_task(
            " ".join(args.task),
            config,
            local_backends,
            cloud_backend,
            system_prompt,
            verbose,
            allow_local=allow_local,
            allow_cloud=allow_cloud,
        )


if __name__ == "__main__":
    main()
