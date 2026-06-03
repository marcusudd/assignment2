"""Stable, human-readable worker lane IDs (realm + file slug)."""
from __future__ import annotations

import re
from pathlib import Path

_REALM = {"local": "midgard", "cloud": "asgard"}


def _slug_part(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "lane"


def file_slug(path: str) -> str:
    """models/order.py → models-order"""
    p = Path(path.replace("\\", "/"))
    stem = _slug_part(p.stem)
    if len(p.parts) >= 2:
        parent = _slug_part(p.parts[-2])
        return f"{parent}-{stem}"
    return stem


def make_lane_id(backend_name: str, owned_files: list[str]) -> str:
    realm = _REALM.get(backend_name, "asgard")
    if owned_files:
        return f"{realm}.{file_slug(owned_files[0])}"
    return f"{realm}.primary"


def assign_worker_id(
    backend_name: str,
    owned_files: list[str],
    used: dict[str, int],
) -> str:
    """Return a unique lane id; bumps suffix on collision (-2, -3, …)."""
    base = make_lane_id(backend_name, owned_files)
    n = used.get(base, 0)
    used[base] = n + 1
    if n == 0:
        return base
    return f"{base}-{n + 1}"
