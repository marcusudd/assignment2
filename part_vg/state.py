"""
Shared state dataclass for the UI ↔ SubAgent bridge.

Workers write to their own WorkerState entry; the UI render-loop reads
all entries under a lock and never calls Rich from a worker thread.
"""
import threading
import time
from dataclasses import dataclass, field


@dataclass
class WorkerState:
    worker_id: str
    role: str
    task_summary: str    # first 60 chars of task for display
    backend: str         # "local" | "cloud" | "cloud (escalated)" …
    model: str
    status: str = "pending"   # pending | running | done | error | aborted
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    start_ts: float | None = None   # monotonic — overlapping = genuine parallel
    end_ts: float | None = None
    current_action: str = ""
    log_lines: list[str] = field(default_factory=list)

    def elapsed(self) -> float | None:
        if self.start_ts is None:
            return None
        end = self.end_ts or time.monotonic()
        return end - self.start_ts

    def append_log(self, line: str) -> None:
        self.log_lines.append(line)
        if len(self.log_lines) > 200:
            self.log_lines = self.log_lines[-200:]


class StateRegistry:
    """Thread-safe collection of WorkerState entries."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._states: dict[str, WorkerState] = {}

    def register(self, ws: WorkerState) -> None:
        with self._lock:
            self._states[ws.worker_id] = ws

    def update(self, worker_id: str, **kwargs) -> None:
        with self._lock:
            ws = self._states.get(worker_id)
            if ws is None:
                return
            for k, v in kwargs.items():
                setattr(ws, k, v)

    def append_log(self, worker_id: str, line: str) -> None:
        with self._lock:
            ws = self._states.get(worker_id)
            if ws:
                ws.append_log(line)

    def snapshot(self) -> list[WorkerState]:
        """Shallow copy of all states for the render loop."""
        import copy
        with self._lock:
            return [copy.copy(ws) for ws in self._states.values()]

    def clear(self) -> None:
        with self._lock:
            self._states.clear()
