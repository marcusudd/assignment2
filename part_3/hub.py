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


def _retryable(resp_status, exc: Exception | None) -> bool:
    """Should this be retried? Only transient errors — never 4xx auth/cap failures."""
    if exc is not None:
        return isinstance(exc, (requests.Timeout, requests.ConnectionError))
    if not isinstance(resp_status, int):
        return False
    return resp_status >= 500  # 5xx server errors are transient


def fetch_messages(since: int) -> list[dict]:
    """Return messages with seq > since. Retries once on transient errors."""
    log = _log.get("hub")
    last_err: Exception | None = None
    for attempt in range(2):
        _throttle()
        t0 = time.time()
        try:
            resp = requests.get(
                f"{HUB_URL}/api/messages",
                params={"since": since, "password": HUB_PASSWORD},
                timeout=10,
            )
            if _retryable(resp.status_code, None) and attempt == 0:
                log.warning("fetch %d, retrying once", resp.status_code)
                time.sleep(1.5)
                continue
            resp.raise_for_status()
            msgs = resp.json().get("messages", [])
            log.debug("GET /api/messages?since=%d → %d msg  %.0fms",
                      since, len(msgs), (time.time() - t0) * 1000)
            return msgs
        except (requests.Timeout, requests.ConnectionError) as e:
            last_err = e
            if attempt == 0:
                log.warning("fetch transient error %s, retrying once", type(e).__name__)
                time.sleep(1.5)
                continue
            raise
    if last_err:
        raise last_err
    return []


def send_message(agent_name: str, content: str) -> int:
    """
    Post a message to the hub. Returns the assigned seq number.
    In dry-run mode just prints and returns -1.
    Retries once on transient errors. Never retries on 429 (rate limit) or 4xx.
    """
    if DRY_RUN:
        print(f"[DRY-RUN] [{agent_name}]: {content[:120]}")
        return -1
    log = _log.get("hub")

    last_err: Exception | None = None
    for attempt in range(2):
        _throttle()
        t0 = time.time()
        try:
            resp = requests.post(
                f"{HUB_URL}/api/message",
                json={"agent_name": agent_name, "content": content, "password": HUB_PASSWORD},
                timeout=10,
            )
            if resp.status_code == 429:
                raise RateLimitError(resp.text)
            if _retryable(resp.status_code, None) and attempt == 0:
                log.warning("send %d, retrying once", resp.status_code)
                time.sleep(1.5)
                continue
            resp.raise_for_status()
            seq = resp.json().get("seq", -1)
            log.info("POST /api/message → seq=%d  %.0fms",
                     seq, (time.time() - t0) * 1000)
            return seq
        except (requests.Timeout, requests.ConnectionError) as e:
            last_err = e
            if attempt == 0:
                log.warning("send transient error %s, retrying once", type(e).__name__)
                time.sleep(1.5)
                continue
            raise
    if last_err:
        raise last_err
    return -1


def fetch_stats() -> dict:
    _throttle()
    resp = requests.get(
        f"{HUB_URL}/api/stats",
        params={"password": HUB_PASSWORD},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()
