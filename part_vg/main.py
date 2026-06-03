"""
Bifrost — entry point.

Usage:
  python main.py "Add /orders endpoint with business logic"
  python main.py --cap 0.05 "List all Python files in the workspace"
  python main.py --interactive          # REPL: run tasks one after another
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
    script = Path(__file__).parent / "scripts" / "reset_seed.sh"
    subprocess.run(["bash", str(script)], check=False)


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
        )

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
    parser.add_argument("--interactive", "-i", action="store_true",
                        help="REPL mode: run tasks one after another, workspace persists")
    args = parser.parse_args()

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
        print("  Commands: 'reset' → restore seed app   'exit' → quit")
        print("  Multi-line / pasted prompts are accepted.")
        print(f"  Cap ${config.cost_cap_usd:.2f} is applied PER task (not session).")
        print("─" * 60)
        while True:
            task = _read_task_input("\n🌉 Task: ")
            if task is None:
                print("\nBye!")
                break
            if not task:
                continue
            if task.lower() in ("exit", "quit", "q"):
                print("Bye!")
                break
            if task.lower() == "reset":
                _reset_workspace()
                print("Workspace reset to seed app.")
                continue

            # Re-resolve backends so LM Studio coming online mid-session is detected.
            local_backends, cloud_backend = resolve(config)
            _run_task(task, config, local_backends, cloud_backend, system_prompt, verbose)
            print()   # blank line before next prompt
    else:
        # ----------------------------------------------------------------
        # Single-shot mode (original behaviour)
        # ----------------------------------------------------------------
        _run_task(
            " ".join(args.task),
            config, local_backends, cloud_backend, system_prompt, verbose,
        )


if __name__ == "__main__":
    main()
