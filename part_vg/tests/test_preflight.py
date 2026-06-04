"""Preflight checks — no network required for env/config slice."""
from pathlib import Path

import pytest

from preflight import run_preflight

ROOT = Path(__file__).resolve().parent.parent


def test_preflight_reports_env_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = run_preflight(
        toml_path=ROOT / "config.toml",
        env_path=tmp_path / "missing.env",
    )
    assert result["ready"] is False
    ids = {c["id"] for c in result["checks"]}
    assert "env_file" in ids
    assert any(c["id"] == "env_file" and not c["ok"] for c in result["checks"])


@pytest.mark.skipif(
    not (ROOT / ".env").is_file(),
    reason="needs project .env for full config load",
)
def test_preflight_with_project_env():
    result = run_preflight(
        toml_path=ROOT / "config.toml",
        env_path=ROOT / ".env",
        api_base="http://127.0.0.1:59999",
    )
    assert "checks" in result
    assert any(c["id"] == "openrouter_key" for c in result["checks"])
