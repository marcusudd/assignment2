from pathlib import Path

import session_log


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
