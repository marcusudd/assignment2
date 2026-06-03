"""
Session log files under logs/ — shared by CLI (main.py) and web server (server.py).
"""
from __future__ import annotations

import io
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, TextIO

LOG_DIR = Path(__file__).parent / "logs"


class Tee(io.TextIOBase):
    """Write to both a stream and a log file."""

    def __init__(self, stream: TextIO, log_file: TextIO) -> None:
        self._stream = stream
        self._log = log_file

    def write(self, s: str) -> int:
        self._stream.write(s)
        self._log.write(s)
        self._log.flush()
        return len(s)

    def flush(self) -> None:
        self._stream.flush()
        try:
            self._log.flush()
        except Exception:
            pass


def _safe_slug(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^\w\-]+", "_", text.strip())[:max_len].strip("_")
    return slug or "task"


def open_session_log(
    task: str,
    *,
    run_id: str | None = None,
) -> tuple[Path, IO[str]]:
    """Create a timestamped log file; return (path, handle)."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    rid = f"_{run_id}" if run_id else ""
    log_path = LOG_DIR / f"{ts}{rid}_{_safe_slug(task)}.log"
    fh = open(log_path, "w", encoding="utf-8")
    fh.write(f"=== Bifrost session {ts} ===\n")
    if run_id:
        fh.write(f"Run ID: {run_id}\n")
    fh.write(f"Task: {task}\n\n")
    fh.flush()
    return log_path, fh


def write_session_summary(
    fh: IO[str],
    *,
    task: str,
    result: str | None,
    snap: dict,
    registry,
    routing: str,
    error: str | None = None,
) -> None:
    fh.write("\n\n=== RESULT ===\n")
    if error:
        fh.write(f"ERROR: {error}\n")
    fh.write((result or "(no result)") + "\n")
    fh.write("\n=== COST ===\n")
    fh.write(f"total: ${snap['total_usd']:.6f} / cap ${snap['cap_usd']:.2f}\n")
    fh.write(f"routing: {routing}\n")

    fh.write("\n=== WORKER LOGS ===\n")
    for ws in registry.snapshot():
        elapsed = ws.elapsed()
        elapsed_str = f"{elapsed:.1f}s" if elapsed else "-"
        fh.write(
            f"\n--- {ws.worker_id} ({ws.role}) "
            f"backend={ws.backend} model={ws.model} "
            f"status={ws.status} elapsed={elapsed_str} "
            f"cost=${ws.cost_usd:.6f} ---\n"
        )
        for line in ws.log_lines:
            fh.write(f"  {line}\n")
    fh.flush()


def list_log_files(limit: int = 30) -> list[dict]:
    """Newest session logs first."""
    if not LOG_DIR.is_dir():
        return []
    entries = []
    for path in LOG_DIR.glob("*.log"):
        if not path.is_file():
            continue
        st = path.stat()
        entries.append(
            {
                "name": path.name,
                "size_bytes": st.st_size,
                "modified_utc": datetime.fromtimestamp(
                    st.st_mtime, tz=timezone.utc
                ).isoformat(),
            }
        )
    entries.sort(key=lambda e: e["modified_utc"], reverse=True)
    return entries[:limit]


def read_log_tail(name: str, max_lines: int = 200) -> str:
    """Read trailing lines from a log file (name must be a bare filename)."""
    if "/" in name or "\\" in name or name.startswith("."):
        raise ValueError("invalid log name")
    path = LOG_DIR / name
    if not path.is_file():
        raise FileNotFoundError(name)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-max_lines:])
