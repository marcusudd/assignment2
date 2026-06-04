import io
from pathlib import Path

import session_log


class _FakeRegistry:
    def snapshot(self):
        return []


_SNAP = {"total_usd": 0.0, "cap_usd": 0.20}


def test_summary_writes_built_section():
    buf = io.StringIO()
    session_log.write_session_summary(
        buf,
        task="t",
        result="done",
        snap=_SNAP,
        registry=_FakeRegistry(),
        routing="Mode 1",
        built=(["models/order.py"], ["main.py"]),
    )
    out = buf.getvalue()
    assert "=== BUILT ===" in out
    assert "+ models/order.py" in out
    assert "~ main.py" in out


def test_summary_built_none_omits_section():
    buf = io.StringIO()
    session_log.write_session_summary(
        buf,
        task="t",
        result="done",
        snap=_SNAP,
        registry=_FakeRegistry(),
        routing="Mode 1",
    )
    assert "=== BUILT ===" not in buf.getvalue()


def test_list_and_tail(tmp_path, monkeypatch):
    monkeypatch.setattr(session_log, "LOG_DIR", tmp_path)
    path, fh = session_log.open_session_log("hello world", run_id="ab12")
    fh.write("line one\nline two\n")
    fh.close()

    files = session_log.list_log_files()
    assert len(files) == 1
    assert files[0]["name"] == path.name

    tail = session_log.read_log_tail(path.name)
    assert "line two" in tail


def test_reject_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(session_log, "LOG_DIR", tmp_path)
    try:
        session_log.read_log_tail("../etc/passwd")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
