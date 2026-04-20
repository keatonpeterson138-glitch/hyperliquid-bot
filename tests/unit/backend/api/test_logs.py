"""API tests for /logs."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.api import logs as logs_api
from backend.main import create_app


def _client_with(tmp_path: Path, lines: list[str]) -> TestClient:
    p = tmp_path / "log.log"
    p.write_text("\n".join(lines) + "\n")
    app = create_app()
    app.dependency_overrides[logs_api.get_log_path] = lambda: p
    return TestClient(app)


def test_tail_returns_last_n(tmp_path) -> None:
    lines = [f"2026-04-20 12:00:{i:02d} INFO foo line {i}" for i in range(30)]
    c = _client_with(tmp_path, lines)
    resp = c.get("/logs", params={"tail": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["lines"]) == 5
    assert body["lines"][-1].endswith("line 29")


def test_level_filter(tmp_path) -> None:
    lines = [
        "2026-04-20 12:00:00 INFO x",
        "2026-04-20 12:00:01 WARNING y",
        "2026-04-20 12:00:02 ERROR z",
    ]
    c = _client_with(tmp_path, lines)
    resp = c.get("/logs", params={"level": "WARNING"})
    assert resp.status_code == 200
    assert all("INFO" not in ln for ln in resp.json()["lines"])


def test_missing_file_returns_empty(tmp_path) -> None:
    app = create_app()
    app.dependency_overrides[logs_api.get_log_path] = lambda: tmp_path / "missing.log"
    c = TestClient(app)
    resp = c.get("/logs")
    assert resp.status_code == 200
    assert resp.json()["lines"] == []


def test_bad_level(tmp_path) -> None:
    c = _client_with(tmp_path, [])
    resp = c.get("/logs", params={"level": "BOGUS"})
    assert resp.status_code == 400


def test_configure_file_logging(tmp_path) -> None:
    path = tmp_path / "logs" / "backend.log"
    returned = logs_api.configure_file_logging(path)
    assert returned == path
    assert path.parent.exists()
    # Emit a log and check it lands.
    import logging
    logging.getLogger(__name__).warning("hello from test")
    for h in list(logging.getLogger().handlers):
        try:
            h.flush()
        except Exception:
            pass
    assert path.exists()
    assert "hello from test" in path.read_text()
