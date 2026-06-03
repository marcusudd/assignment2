"""
Rich-based FinOps dashboard (VG.3, D7).

Architecture:
- Workers write to StateRegistry (thread-safe, behind a lock).
- A single render thread owns the Rich Live context and polls the registry
  at ~250 ms intervals. Workers NEVER touch Rich directly.

Layout (simple mode, always present):
  ┌ header: task + status ──────────────────────────────────────┐
  │ worker table: id | backend | model | tokens | cost | status │
  │ cost bar: $actual / $cap  ██████░░░░  4.2%  [WARNING]       │
  │ routing: "Mode 3 — decomposed into 4 workers (2L / 2C)"     │
  │ savings panel: 9 comparison models                          │
  └─────────────────────────────────────────────────────────────┘

Utförlig mode (toggled via --verbose / always on in demo):
  same as above + per-worker scrolling log at the bottom.
"""
import threading
import time
from typing import Callable

from rich.columns import Columns
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn
from rich.table import Table
from rich.text import Text

from cost import CostTracker
from state import StateRegistry, WorkerState

_POLL_INTERVAL = 0.25   # seconds between render ticks
_BACKEND_ICON = {"local": "🏠", "cloud": "☁️"}


def _backend_icon(backend: str) -> str:
    for k, v in _BACKEND_ICON.items():
        if k in backend:
            return v
    return "?"


def _status_style(status: str) -> str:
    return {
        "pending": "dim",
        "running": "bold cyan",
        "done": "green",
        "error": "bold red",
        "aborted": "yellow",
    }.get(status, "white")


def _worker_table(states: list[WorkerState]) -> Table:
    t = Table(box=None, show_header=True, header_style="bold")
    t.add_column("Worker", style="dim", width=12)
    t.add_column("Backend", width=22)
    t.add_column("Model", width=24)
    t.add_column("Tokens", justify="right", width=8)
    t.add_column("Cost", justify="right", width=9)
    t.add_column("Elapsed", justify="right", width=7)
    t.add_column("Status", width=22)

    for ws in states:
        icon = _backend_icon(ws.backend)
        tokens = ws.prompt_tokens + ws.completion_tokens
        elapsed = ws.elapsed()
        elapsed_str = f"{elapsed:.1f}s" if elapsed is not None else "-"
        status_text = Text(ws.status, style=_status_style(ws.status))
        if ws.current_action and ws.status == "running":
            action = ws.current_action
            if "BLOCKED" in action or "error" in action.lower():
                style = "bold red"
            elif "creating" in action or "editing" in action:
                style = "bold green"
            elif "reading" in action:
                style = "dim cyan"
            elif "thinking" in action:
                style = "bold yellow"
            elif "$ " in action:
                style = "magenta"
            else:
                style = "cyan"
            status_text = Text(action[:28], style=style)
        t.add_row(
            ws.worker_id,
            f"{icon} {ws.backend[:18]}",
            ws.model[:22],
            str(tokens),
            f"${ws.cost_usd:.4f}",
            elapsed_str,
            status_text,
        )
    return t


def _cost_bar(tracker: CostTracker) -> Panel:
    snap = tracker.snapshot()
    total = snap["total_usd"]
    cap = snap["cap_usd"]
    frac = min(snap["fraction"], 1.0)
    pct = frac * 100

    bar_width = 30
    filled = int(bar_width * frac)
    bar_color = "red" if frac >= 1.0 else ("yellow" if tracker.is_warning() else "green")
    bar = f"[{bar_color}]{'█' * filled}[/{bar_color}]{'░' * (bar_width - filled)}"

    warning = "  [bold red]⚠ WARNING[/bold red]" if tracker.is_warning() else ""
    stopped = "  [bold red]■ STOPPED[/bold red]" if tracker.should_stop() else ""
    label = f"${total:.4f} / ${cap:.2f}  {bar}  {pct:.1f}%{warning}{stopped}"
    return Panel(label, title="Budget", border_style="dim")


def _savings_panel(tracker: CostTracker, comparison_models: list[str]) -> Panel:
    if not comparison_models:
        return Panel("(no comparison models configured)", title="Savings")
    cf = tracker.counterfactual(comparison_models)
    snap = tracker.snapshot()
    actual = snap["total_usd"]

    rows: list[str] = []
    for model, cost in sorted(cf.items(), key=lambda x: -x[1]):
        saved = cost - actual
        saved_str = f"save ${saved:.4f}" if saved > 0 else f"no saving"
        rows.append(f"  {model:<40} ${cost:.4f}  ({saved_str})")

    return Panel(
        "\n".join(rows) if rows else "(computing…)",
        title=f"All-cloud cost comparison  (actual: ${actual:.4f})",
        border_style="dim",
    )


def _gantt_panel(states: list[WorkerState], width: int = 44, *, live: bool = True) -> Panel:
    """Show each worker as a bar on a shared timeline (VG.1 visual proof).

    All bars are anchored to the earliest start_ts, so overlapping bars make
    genuine parallelism obvious at a glance. Local workers against one LM Studio
    instance show a stair-step (they queue); cloud workers and dual-local
    workers overlap fully.
    """
    started = [s for s in states if s.start_ts is not None]
    if not started:
        return Panel("(waiting for workers to start…)", title="Parallel timeline",
                     border_style="dim")

    t0 = min(s.start_ts for s in started)
    now = time.monotonic()
    if live:
        t_end = max((s.end_ts or now) for s in started)
    else:
        t_end = max((s.end_ts or s.start_ts or t0) for s in started)
    span = max(t_end - t0, 0.001)   # avoid div-by-zero

    bar_style = {
        "done": "green", "running": "cyan", "error": "red", "aborted": "yellow",
    }

    rows: list[str] = []
    for ws in states:
        icon = _backend_icon(ws.backend)
        if ws.start_ts is None:
            rows.append(f"{ws.worker_id:<11} {icon}  [dim]pending[/dim]")
            continue
        start_off = (ws.start_ts - t0) / span
        if live and ws.end_ts is None and ws.status in ("running", "pending"):
            end_ts = now
        else:
            end_ts = ws.end_ts or ws.start_ts or t0
        end_off = (end_ts - t0) / span
        lead = int(start_off * width)
        length = max(int((end_off - start_off) * width), 1)
        trail = width - lead - length
        if trail < 0:
            trail = 0
        color = bar_style.get(ws.status, "white")
        bar = (" " * lead) + f"[{color}]" + ("▰" * length) + f"[/{color}]" + ("·" * trail)
        elapsed = ws.elapsed() or 0.0
        rows.append(f"{ws.worker_id:<11} {icon} {bar} {ws.status:<8} {elapsed:5.1f}s")

    axis = f"{'':<14}0s{' ' * (width - 6)}{span:4.0f}s"
    body = "\n".join(rows) + "\n" + f"[dim]{axis}[/dim]"
    return Panel(body, title="Parallel timeline (anchored to first start)",
                 border_style="dim")


def _log_panel(states: list[WorkerState], lines: int = 12) -> Panel:
    log_lines: list[str] = []
    for ws in states:
        for line in ws.log_lines[-lines:]:
            log_lines.append(f"[dim][{ws.worker_id}][/dim] {line}")
    visible = log_lines[-(lines * len(states)):]
    return Panel("\n".join(visible) or "(no logs yet)", title="Activity log", border_style="dim")


class Dashboard:
    def __init__(
        self,
        task: str,
        registry: StateRegistry,
        cost_tracker: CostTracker,
        comparison_models: list[str],
        verbose: bool = True,
    ) -> None:
        self.task = task
        self.registry = registry
        self.cost_tracker = cost_tracker
        self.comparison_models = comparison_models
        self.verbose = verbose
        self.routing_summary: str = "Routing…"
        self._console = Console()
        self._live: Live | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def set_routing_summary(self, summary: str) -> None:
        self.routing_summary = summary

    def start(self) -> None:
        self._live = Live(
            self._render(),
            console=self._console,
            refresh_per_second=4,
            screen=False,
        )
        self._live.__enter__()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        if self._live:
            self._live.update(self._render())
            self._live.__exit__(None, None, None)

    def _loop(self) -> None:
        while not self._stop.is_set():
            if self._live:
                self._live.update(self._render())
            time.sleep(_POLL_INTERVAL)

    def _render(self):
        states = self.registry.snapshot()
        all_done = all(ws.status in ("done", "error", "aborted") for ws in states) if states else False
        span_live = not all_done and not self.cost_tracker.should_stop()
        status_label = "[green]DONE[/green]" if all_done else "[bold cyan]RUNNING[/bold cyan]"

        parts = [
            Panel(
                f"[bold]{self.task[:90]}[/bold]  {status_label}",
                title="Bifrost",
                border_style="blue",
            ),
            _worker_table(states),
            _gantt_panel(states, live=span_live),
            _cost_bar(self.cost_tracker),
            Panel(self.routing_summary, title="Router decision", border_style="dim"),
            _savings_panel(self.cost_tracker, self.comparison_models),
        ]
        if self.verbose and states:
            parts.append(_log_panel(states))

        from rich.console import Group
        return Group(*parts)
