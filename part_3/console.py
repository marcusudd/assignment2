"""
Local control console — runs in a background thread, reads stdin commands.
Lets Marcus chat privately with the agent, steer its group behaviour, post to the
hub, and adjust caps / pause-resume the loop in real-time. Rendered with rich.
"""

import os
import threading

from rich.console import Console as RichConsole
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

import agent as ag
import hub
import trace as tr

rc = RichConsole()

_HELP_ROWS = [
    ("ask <text>", "chat PRIVATELY with your agent (local only — not posted)"),
    ("steer <text>", "privately steer how it behaves in the GROUP chat"),
    ("steer off", "clear the private steering"),
    ("say <text>", "post a message to the hub as you (the human)"),
    ("status", "msg count, token usage, pause state, steering"),
    ("pause | resume", "stop / restart the polling loop"),
    ("cap <N>", "change token cap on the fly"),
    ("limit <N>", "change per-session message cap"),
    ("y | n", "approve / deny a pending bash command"),
    ("trace [N]", "last N decision events (PASS, LLM, tools, routing)"),
    ("trace on | off", "mirror new trace lines into this console"),
    ("help", "show this panel again"),
    ("quit", "shut the agent down cleanly"),
]


def _help_panel() -> Panel:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold cyan", no_wrap=True)
    table.add_column(style="white")
    for cmd, desc in _HELP_ROWS:
        table.add_row(cmd, desc)
    return Panel(
        table,
        title="[bold]console ready[/]",
        subtitle="[dim]detach with Ctrl-P Ctrl-Q · Ctrl-C kills the agent[/]",
        border_style="cyan",
    )


class Console(threading.Thread):
    def __init__(self, state: "AgentState") -> None:
        super().__init__(daemon=True)
        self.state = state
        self.agent_name = ag.AGENT_NAME
        self._trace_listener = None
        # Private Q&A channel state — its own prompt + history, shared token budget.
        self._private_prompt: str | None = None
        self._private_history: list = []

    def run(self) -> None:
        rc.print(_help_panel())
        while True:
            try:
                line = rc.input("[bold cyan]› [/]").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not line:
                continue
            try:
                self._handle(line)
            except Exception as e:  # never let a bad command kill the console
                rc.print(f"[red]console error:[/] {e}")

    def _handle(self, line: str) -> None:
        parts = line.split()
        cmd = parts[0].lower()

        if cmd in ("y", "n"):
            if ag.bash_approval.pending:
                ag.bash_approval.respond(cmd)
                rc.print(f"[green]bash approved ✓[/]" if cmd == "y" else "[red]bash denied ✗[/]")
            else:
                rc.print("[dim]no bash command pending[/]")

        elif cmd in ("help", "?"):
            rc.print(_help_panel())

        elif cmd == "status":
            self._status()

        elif cmd == "cap" and len(parts) == 2:
            try:
                self.state.token_counter.cap = int(parts[1])
                rc.print(f"[green]token cap → {parts[1]}[/]")
            except ValueError:
                rc.print("[yellow]usage: cap <number>[/]")

        elif cmd == "limit" and len(parts) == 2:
            try:
                self.state.msg_cap = int(parts[1])
                rc.print(f"[green]message limit → {parts[1]}[/]")
            except ValueError:
                rc.print("[yellow]usage: limit <number>[/]")

        elif cmd == "pause":
            self.state.paused = True
            rc.print("[yellow]agent paused[/]")

        elif cmd == "resume":
            self.state.paused = False
            rc.print("[green]agent resumed[/]")

        elif cmd == "quit":
            self.state.running = False
            rc.print("[red]shutting down…[/]")

        elif cmd == "steer":
            self._steer(line[5:].strip())

        elif cmd == "say":
            self._say(line[3:].strip())

        elif cmd == "ask":
            self._ask(line[3:].strip())

        elif cmd == "trace":
            self._trace(parts[1:] if len(parts) > 1 else [])

        else:
            rc.print(
                "[dim]unknown command. try:[/] ask · steer · say · status · trace · "
                "cap N · limit N · pause · resume · y · n · help · quit"
            )

    # ----- command implementations -------------------------------------------
    def _status(self) -> None:
        s = self.state
        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold")
        table.add_column()
        table.add_row("messages", f"{s.messages_sent}/{s.msg_cap}")
        table.add_row("tokens", f"{s.token_counter.total}/{s.token_counter.cap}")
        table.add_row("paused", "yes" if s.paused else "no")
        table.add_row("last seq", str(s.last_seen))
        steer = s.private_steer or "[dim](none)[/]"
        table.add_row("steering", steer)
        table.add_row("trace mirror", "on" if self.state.trace_mirror else "off")
        table.add_row("trace log", "on" if tr.TRACE_TO_LOG else "off (set TRACE=1 in .env)")
        rc.print(Panel(table, title="status", border_style="blue"))

    def _trace_mirror_cb(self, entry: dict) -> None:
        rc.print(f"[dim]{tr.format_entry(entry, detail_max=120)}[/]")

    def _set_trace_mirror(self, on: bool) -> None:
        self.state.trace_mirror = on
        if self._trace_listener is not None:
            tr.unregister_listener(self._trace_listener)
            self._trace_listener = None
        if on:
            self._trace_listener = self._trace_mirror_cb
            tr.register_listener(self._trace_listener)
            rc.print("[green]trace mirror on[/] — new events appear here")
        else:
            rc.print("[yellow]trace mirror off[/]")

    def _trace(self, args: list[str]) -> None:
        if args and args[0].lower() in ("on", "off"):
            self._set_trace_mirror(args[0].lower() == "on")
            return
        n = 25
        if args:
            try:
                n = max(1, min(100, int(args[0])))
            except ValueError:
                rc.print("[yellow]usage: trace [N] | trace on | trace off[/]")
                return
        items = tr.get_recent(n)
        if not items:
            rc.print("[dim]no trace events yet[/]")
            return
        body = "\n\n".join(tr.format_entry(e) for e in items)
        rc.print(Panel(body, title=f"decision trace (last {len(items)})", border_style="dim cyan"))

    def _steer(self, text: str) -> None:
        if not text or text.lower() in ("off", "clear", "none"):
            self.state.private_steer = ""
            rc.print("[green]steering cleared[/]")
            return
        self.state.private_steer = text
        rc.print(Panel(text, title="private steering set", border_style="magenta"))

    def _say(self, text: str) -> None:
        if not text:
            rc.print("[yellow]usage: say <message>[/]")
            return
        poster = os.getenv("CONSOLE_POSTER", "human:marcus")
        try:
            hub.send_message(poster, text)
            rc.print(f"[green]posted to hub as[/] [cyan]{poster}[/]")
        except Exception as e:
            rc.print(f"[red]post failed:[/] {e}")

    def _ask(self, text: str) -> None:
        if not text:
            rc.print("[yellow]usage: ask <question>[/]")
            return
        if self._private_prompt is None:
            try:
                self._private_prompt = ag.load_private_prompt()
            except OSError as e:
                rc.print(f"[red]could not load config/private_prompt.txt:[/] {e}")
                return
        # The private channel is the human's own — let its tool calls auto-approve so
        # `ask` never deadlocks waiting on the same thread to type y/n. Restored after.
        prev_auto = ag.AUTO_APPROVE
        ag.AUTO_APPROVE = True
        try:
            with rc.status("[dim]thinking…[/]"):
                reply = ag.decide(
                    [{"agent_name": "marcus-human", "content": text}],
                    self.agent_name,
                    self._private_prompt,
                    self._private_history,
                    self.state.token_counter,
                )
        except Exception as e:
            rc.print(f"[red]ask failed:[/] {e}")
            return
        finally:
            ag.AUTO_APPROVE = prev_auto
        if not reply or reply.upper() == "PASS":
            rc.print("[dim](no answer)[/]")
            return
        rc.print(Panel(Markdown(reply), title=f"{self.agent_name} (private)", border_style="green"))


class AgentState:
    def __init__(self, msg_cap: int, token_counter) -> None:
        self.messages_sent: int = 0
        self.msg_cap: int = msg_cap
        self.last_seen: int = 0
        self.paused: bool = False
        self.running: bool = True
        self.token_counter = token_counter
        self.token_signoff_sent: bool = False
        self.soft_limit_logged: bool = False
        self.silence_active: bool = False
        # Agent who claimed manager/coordinator in chat (e.g. ErikMoren-agent).
        self.peer_manager: str | None = None
        # Set after posting one solicited [ROSTER] line for a manager roll-call.
        self.roster_posted: bool = False
        # Set after posting one [CLAIM] for an open manager task slice.
        self.claim_posted: bool = False
        # Private steering set by the human via the console `steer` command. Injected
        # into the active prompt as a private operator directive that shapes how the
        # agent behaves in the GROUP chat — never posted, invisible to other agents.
        self.private_steer: str = ""
        # Pinned "important messages" — compact one-liners (role claims, deliveries,
        # direct @mentions with a task) that must survive history trimming. main.py's
        # update_pinned_memory fills this; build_active_prompt injects it as SESSION
        # MEMORY so the agent still knows who owns what after old chat is cut.
        self.pinned_memory: list[str] = []
        # Track the last canned-fallback message so we don't repeat it back-to-back
        self.last_canned_at: float = 0.0
        self.last_canned_text: str = ""
        self.last_autosum_text: str = ""
        self.last_autosum_at: float = 0.0
        # Sticky operator directive — survives across polling cycles until task
        # completes or a newer operator imperative arrives. Without this the
        # nudge stops firing once the operator's message is no longer in the
        # current poll batch, and agents PASS forever on multi-step tasks.
        self.active_op_cmd: str | None = None
        self.active_op_seq: int = 0
        # Peer-file health tracking — populated by auto_save_peer_code when a
        # delivered file looks broken (truncated, syntax error, conflicting).
        # Surfaced in workspace gap so the LLM can decide to ask for a repost
        # or rewrite locally. {filename: "truncated"|"syntax: ..."|"conflict"}
        self.peer_file_issues: dict[str, str] = {}
        # Circuit breaker: count consecutive ABORTs (promise/non-delivery).
        # After N in a row, force PASS for one round to break a stuck retry
        # loop that would otherwise burn the token budget without delivering.
        self.consecutive_aborts: int = 0
        # Mirror trace.record() events into the rich console (`trace on`).
        self.trace_mirror: bool = False
        self.last_heartbeat_at: float = 0.0
        # Buffer for split CODE TRANSFER messages: {fname: {part_n: code, ...}}
        # When a peer posts a file as "(part 1/N)" + "(part 2/N)" etc., we buffer
        # each part here and concatenate when all N parts have arrived. Saves the
        # full file deterministically rather than asking peer to repost.
        self.split_transfer_buffer: dict[str, dict[int, str]] = {}
        self.split_transfer_meta: dict[str, dict] = {}  # {fname: {"total": N, "peer": str, "last_seq": int}}

    def at_cap(self) -> bool:
        return self.messages_sent >= self.msg_cap
