"""
Local control console — runs in a background thread, reads stdin commands.
Lets Marcus adjust caps and pause/resume the agent loop in real-time.
"""

import os
import threading
import agent as ag
import hub


class Console(threading.Thread):
    def __init__(self, state: "AgentState") -> None:
        super().__init__(daemon=True)
        self.state = state

    def run(self) -> None:
        print(
            "\n"
            "──────────────────────── console ready ────────────────────────\n"
            " say <text>       post a message to the hub as you (the human)\n"
            " status           show msg count, token usage, pause state\n"
            " pause | resume   stop / restart the polling loop\n"
            " cap <N>          change token cap on the fly\n"
            " limit <N>        change per-session message cap\n"
            " y | n            approve / deny a pending bash command\n"
            " quit             shut the agent down cleanly\n"
            "───────────────────────────────────────────────────────────────\n"
            " Tip: type   say hi team   to introduce yourself to the chat.\n",
            flush=True,
        )
        while True:
            try:
                line = input().strip()
            except EOFError:
                break
            if not line:
                continue
            self._handle(line)

    def _handle(self, line: str) -> None:
        parts = line.split()
        cmd = parts[0].lower()

        if cmd in ("y", "n"):
            if ag.bash_approval.pending:
                ag.bash_approval.respond(cmd)
                print(f"[console] bash {'approved ✓' if cmd == 'y' else 'denied ✗'}")
            else:
                print("[console] no bash command pending")

        elif cmd == "status":
            s = self.state
            print(
                f"[status] msgs_sent={s.messages_sent}/{s.msg_cap}  "
                f"tokens={s.token_counter.total}/{s.token_counter.cap}  "
                f"paused={s.paused}  last_seq={s.last_seen}"
            )

        elif cmd == "cap" and len(parts) == 2:
            try:
                self.state.token_counter.cap = int(parts[1])
                print(f"[console] token cap set to {parts[1]}")
            except ValueError:
                print("[console] usage: cap <number>")

        elif cmd == "limit" and len(parts) == 2:
            try:
                self.state.msg_cap = int(parts[1])
                print(f"[console] message limit set to {parts[1]}")
            except ValueError:
                print("[console] usage: limit <number>")

        elif cmd == "pause":
            self.state.paused = True
            print("[console] agent paused")

        elif cmd == "resume":
            self.state.paused = False
            print("[console] agent resumed")

        elif cmd == "quit":
            self.state.running = False
            print("[console] shutting down…")

        elif cmd == "say":
            text = line[3:].strip()  # everything after "say " — preserve case/spaces
            if not text:
                print("[console] usage: say <message>")
                return
            poster = os.getenv("CONSOLE_POSTER", "human:marcus")
            try:
                hub.send_message(poster, text)
                print(f"[console] posted to hub as `{poster}`")
            except Exception as e:
                print(f"[console] post failed: {e}")

        else:
            print(
                "[console] unknown command. try: y | n | status | cap N | limit N | "
                "pause | resume | quit | say <message>"
            )


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
        # Track the last canned-fallback message so we don't repeat it back-to-back
        self.last_canned_at: float = 0.0
        self.last_canned_text: str = ""
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
        # Buffer for split CODE TRANSFER messages: {fname: {part_n: code, ...}}
        # When a peer posts a file as "(part 1/N)" + "(part 2/N)" etc., we buffer
        # each part here and concatenate when all N parts have arrived. Saves the
        # full file deterministically rather than asking peer to repost.
        self.split_transfer_buffer: dict[str, dict[int, str]] = {}
        self.split_transfer_meta: dict[str, dict] = {}  # {fname: {"total": N, "peer": str, "last_seq": int}}

    def at_cap(self) -> bool:
        return self.messages_sent >= self.msg_cap
