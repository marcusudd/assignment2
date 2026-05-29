"""
Centralised logging — writes to stdout and logs/{agent_name}.log.
Usage: log = log.get(); log.info("...")
"""

import logging
import os
import sys
from pathlib import Path

_loggers: dict[str, logging.Logger] = {}

_STDOUT_FMT = "%(asctime)s [%(levelname).1s] %(message)s"
_FILE_FMT   = "%(asctime)s [%(levelname)s] %(message)s"
_DATE_SHORT = "%H:%M:%S"
_DATE_LONG  = "%Y-%m-%d %H:%M:%S"


def get(suffix: str = "") -> logging.Logger:
    agent = os.getenv("AGENT_NAME", "agent")
    name = f"{agent}.{suffix}" if suffix else agent
    if name in _loggers:
        return _loggers[name]

    debug = os.getenv("DEBUG", "").lower() in ("1", "true")
    level = logging.DEBUG if debug else logging.INFO

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False

    # QUIET_STDOUT=1 → file logging only (use when attached to a console
    # terminal and you don't want INFO log noise scrolling over your typing).
    if os.getenv("QUIET_STDOUT", "").lower() not in ("1", "true"):
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(logging.Formatter(_STDOUT_FMT, datefmt=_DATE_SHORT))
        sh.setLevel(level)
        logger.addHandler(sh)

    try:
        logs_dir = Path("logs")
        logs_dir.mkdir(exist_ok=True)
        fh = logging.FileHandler(logs_dir / f"{agent}.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter(_FILE_FMT, datefmt=_DATE_LONG))
        fh.setLevel(logging.DEBUG)
        logger.addHandler(fh)
    except OSError:
        pass

    _loggers[name] = logger
    return logger
