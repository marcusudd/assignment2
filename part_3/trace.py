"""
Decision trace — ring buffer of routing, PASS, LLM, and tool events.

Set TRACE=1 (or LOG_TRACE=1) to mirror each event to logs at INFO as [trace] lines.
Use the console `trace` command to read recent events; `trace on` mirrors live.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from datetime import datetime
from typing import Callable

_MAX = int(os.getenv("TRACE_BUFFER_SIZE", "100"))
TRACE_TO_LOG = os.getenv("TRACE", "").lower() in ("1", "true") or os.getenv(
    "LOG_TRACE", "",
).lower() in ("1", "true")

_buffer: deque[dict] = deque(maxlen=_MAX)
_lock = threading.Lock()
_listeners: list[Callable[[dict], None]] = []


def record(kind: str, summary: str, detail: str = "") -> None:
    entry = {
        "t": time.time(),
        "kind": kind.upper(),
        "summary": summary,
        "detail": (detail or "")[:4000],
    }
    with _lock:
        _buffer.append(entry)
        listeners = list(_listeners)
    if TRACE_TO_LOG:
        import log as _log

        line = f"[trace] {entry['kind']}: {summary}"
        if entry["detail"]:
            line += f" | {entry['detail'][:500]}"
        _log.get("trace").info(line)
    for fn in listeners:
        try:
            fn(entry)
        except Exception:
            pass


def get_recent(n: int = 30) -> list[dict]:
    with _lock:
        items = list(_buffer)
    return items[-n:]


def format_entry(entry: dict, *, detail_max: int = 200) -> str:
    ts = datetime.fromtimestamp(entry["t"]).strftime("%H:%M:%S")
    line = f"{ts} [{entry['kind']}] {entry['summary']}"
    if entry.get("detail"):
        d = entry["detail"]
        if len(d) > detail_max:
            d = d[: detail_max - 1] + "…"
        line += f"\n    {d}"
    return line


def register_listener(fn: Callable[[dict], None]) -> None:
    with _lock:
        if fn not in _listeners:
            _listeners.append(fn)


def unregister_listener(fn: Callable[[dict], None]) -> None:
    with _lock:
        try:
            _listeners.remove(fn)
        except ValueError:
            pass


def clear() -> None:
    with _lock:
        _buffer.clear()
