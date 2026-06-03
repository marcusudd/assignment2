"""Tests for StateRegistry — manual-compaction flag semantics."""
from state import StateRegistry


def test_should_compact_peeks_without_clearing():
    reg = StateRegistry()
    assert reg.should_compact() is False

    reg.request_compact()
    # Peek must stay True until a compaction actually runs (clear_compact).
    assert reg.should_compact() is True
    assert reg.should_compact() is True


def test_clear_compact_resets_flag():
    reg = StateRegistry()
    reg.request_compact()
    assert reg.should_compact() is True

    reg.clear_compact()
    assert reg.should_compact() is False
