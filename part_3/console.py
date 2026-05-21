"""
Local control console — runs in a background thread, reads stdin commands.
Lets Marcus adjust caps and pause/resume the agent loop in real-time.
"""

import threading
import agent as ag


class Console(threading.Thread):
    def __init__(self, state: "AgentState") -> None:
        super().__init__(daemon=True)
        self.state = state

    def run(self) -> None:
        print("[console] ready — commands: y | n | status | cap N | limit N | pause | resume | quit")
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

        else:
            print("[console] unknown command. try: y | n | status | cap N | limit N | pause | resume | quit")


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
