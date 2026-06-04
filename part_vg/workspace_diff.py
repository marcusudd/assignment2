"""
Workspace snapshots — used by main.py to report what a run actually built.

Pure functions (no I/O side effects beyond reading the filesystem) so they can
be unit-tested without an agent run.
"""
from pathlib import Path

_IGNORED_DIRS = {"__pycache__", ".pytest_cache", ".git"}


def snapshot_workspace(workspace_dir: str) -> dict[str, float]:
    """Map each workspace file (relative path) to its mtime.

    Skips generated/cache dirs so they never show up as "built".
    """
    root = Path(workspace_dir)
    snap: dict[str, float] = {}
    if not root.is_dir():
        return snap
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _IGNORED_DIRS for part in path.relative_to(root).parts):
            continue
        snap[str(path.relative_to(root))] = path.stat().st_mtime
    return snap


def diff_workspace(
    before: dict[str, float], after: dict[str, float]
) -> tuple[list[str], list[str]]:
    """Return (created, modified) sorted relative paths between two snapshots."""
    created = sorted(f for f in after if f not in before)
    modified = sorted(f for f in after if f in before and after[f] > before[f])
    return created, modified
