"""Tests for workspace snapshot/diff used by the terminal run summary."""
from pathlib import Path

from workspace_diff import diff_workspace, snapshot_workspace


def test_snapshot_lists_files_skips_cache(tmp_path: Path):
    (tmp_path / "main.py").write_text("x = 1\n")
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "item.py").write_text("y = 2\n")
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "main.cpython-312.pyc").write_text("junk")

    snap = snapshot_workspace(str(tmp_path))

    assert set(snap) == {"main.py", "models/item.py"}


def test_snapshot_missing_dir_returns_empty():
    assert snapshot_workspace("/nonexistent/path/xyz") == {}


def test_diff_detects_created_and_modified(tmp_path: Path):
    (tmp_path / "keep.py").write_text("v = 1\n")
    before = snapshot_workspace(str(tmp_path))

    # New file
    (tmp_path / "new.py").write_text("n = 1\n")
    # Modify existing file with a strictly newer mtime
    keep = tmp_path / "keep.py"
    keep.write_text("v = 2\n")
    bumped = before["keep.py"] + 10
    import os
    os.utime(keep, (bumped, bumped))

    after = snapshot_workspace(str(tmp_path))
    created, modified = diff_workspace(before, after)

    assert created == ["new.py"]
    assert modified == ["keep.py"]


def test_diff_no_changes(tmp_path: Path):
    (tmp_path / "a.py").write_text("1\n")
    snap = snapshot_workspace(str(tmp_path))
    created, modified = diff_workspace(snap, snap)
    assert created == []
    assert modified == []
