"""
Hub client — HTTPS REST API for the group chat server.
"""

import os
import time
import requests
import log as _log

HUB_URL = os.getenv("HUB_URL", "https://wb48jtfnjng6on-8080.proxy.runpod.net")
HUB_PASSWORD = os.getenv("HUB_PASSWORD", "th25-agents-vg")
DRY_RUN = os.getenv("DRY_RUN", "true").lower() in ("1", "true")

_last_request_time: float = 0.0


class RateLimitError(Exception):
    pass


def _throttle() -> None:
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < 1.0:
        time.sleep(1.0 - elapsed)
    _last_request_time = time.time()


def fetch_messages(since: int) -> list[dict]:
    """Return messages with seq > since."""
    log = _log.get("hub")
    _throttle()
    t0 = time.time()
    resp = requests.get(
        f"{HUB_URL}/api/messages",
        params={"since": since, "password": HUB_PASSWORD},
        timeout=10,
    )
    resp.raise_for_status()
    msgs = resp.json().get("messages", [])
    log.debug("GET /api/messages?since=%d → %d msg  %.0fms", since, len(msgs), (time.time() - t0) * 1000)
    return msgs


def send_message(agent_name: str, content: str) -> int:
    """
    Post a message to the hub. Returns the assigned seq number.
    In dry-run mode just prints and returns -1.
    """
    if DRY_RUN:
        print(f"[DRY-RUN] [{agent_name}]: {content[:120]}")
        return -1
    log = _log.get("hub")

    _throttle()
    t0 = time.time()
    resp = requests.post(
        f"{HUB_URL}/api/message",
        json={"agent_name": agent_name, "content": content, "password": HUB_PASSWORD},
        timeout=10,
    )
    if resp.status_code == 429:
        raise RateLimitError(resp.text)
    resp.raise_for_status()
    seq = resp.json().get("seq", -1)
    log.info("POST /api/message → seq=%d  %.0fms", seq, (time.time() - t0) * 1000)
    return seq


def fetch_stats() -> dict:
    _throttle()
    resp = requests.get(
        f"{HUB_URL}/api/stats",
        params={"password": HUB_PASSWORD},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()
