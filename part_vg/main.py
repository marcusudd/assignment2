"""
Bifrost — entry point.

Usage:
  python main.py "Add /orders endpoint with business logic"
  python main.py --cap 0.05 "List all Python files in the workspace"
  python main.py --no-verbose "Refactor payment.py to use async/await"

All options can also be set via config.toml / .env.
"""
import argparse
import sys
import time
from pathlib import Path


def _load_system_prompt(config) -> str:
    here = Path(__file__).parent
    path = here / "config" / "system_prompt.txt"
    text = path.read_text(encoding="utf-8")
    # tool_bash prepends Bifrost's venv bin to PATH, so bare `python3`
    # resolves to the interpreter that has the demo deps (local + Docker).
    return (
        text
        .replace("{workspace_dir}", str(Path(config.workspace_dir).resolve()))
        .replace("{max_output}", str(config.max_output))
        .replace("{python_cmd}", "python3")
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="bifrost",
        description="Local-first hybrid coding agent with cost transparency",
    )
    parser.add_argument("task", nargs="+", help="Task description")
    parser.add_argument("--cap", type=float, help="Override cost cap (USD)")
    parser.add_argument("--config", default="config.toml", help="Config file path")
    parser.add_argument("--no-verbose", action="store_true", help="Simple UI (no per-worker log)")
    args = parser.parse_args()

    task = " ".join(args.task)

    # --- Config ---
    from config import Config
    config = Config.load(toml_path=args.config)
    if args.cap is not None:
        config.cost_cap_usd = args.cap

    # Ensure workspace exists
    Path(config.workspace_dir).mkdir(parents=True, exist_ok=True)

    # --- Backends ---
    from backends import resolve
    local_backend, cloud_backend = resolve(config)

    # --- Cost tracker ---
    from cost import CostTracker
    prices_path = Path(__file__).parent / "model_prices.json"
    cost_tracker = CostTracker(
        cap_usd=config.cost_cap_usd,
        warning_threshold=config.cost_warning_threshold,
        prices_path=str(prices_path),
    )

    # --- State registry ---
    from state import StateRegistry
    registry = StateRegistry()

    # --- UI ---
    from ui import Dashboard
    verbose = not args.no_verbose
    dashboard = Dashboard(
        task=task,
        registry=registry,
        cost_tracker=cost_tracker,
        comparison_models=config.comparison_models,
        verbose=verbose,
    )

    # --- System prompt ---
    system_prompt = _load_system_prompt(config)

    # --- Orchestrator ---
    from orchestrator import Orchestrator
    orch = Orchestrator(
        config=config,
        local_backend=local_backend,
        cloud_backend=cloud_backend,
        cost_tracker=cost_tracker,
        registry=registry,
        worker_system_prompt=system_prompt,
    )

    # --- Run ---
    dashboard.start()
    try:
        result = orch.run(task)
        # Let routing summary propagate to UI
        dashboard.set_routing_summary(orch.routing_summary)
        time.sleep(0.5)   # let final render tick fire
    except KeyboardInterrupt:
        result = "Interrupted by user."
    finally:
        dashboard.stop()

    # --- Final output ---
    print("\n" + "=" * 60)
    print("Result:")
    print(result)
    print("=" * 60)

    snap = cost_tracker.snapshot()
    print(f"\nFinal cost: ${snap['total_usd']:.4f} / ${snap['cap_usd']:.2f}")

    cf = cost_tracker.counterfactual(config.comparison_models)
    if cf:
        print("\nAll-cloud comparison:")
        for model, cost in sorted(cf.items(), key=lambda x: -x[1]):
            saved = cost - snap["total_usd"]
            print(f"  {model:<40} ${cost:.4f}  (saved ${saved:.4f})")


if __name__ == "__main__":
    main()
