"""API tests for /killswitch."""
from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api import killswitch as ks_api
from backend.db.app_db import AppDB
from backend.main import create_app
from backend.services.audit import AuditService
from backend.services.kill_switch import KillSwitchService


class FakeExchange:
    def cancel_all(self):
        return [{"oid": 1}]

    def get_all_positions(self):
        return [{"symbol": "BTC"}]

    def close_position(self, symbol, dex=""):
        return {"status": "closed", "symbol": symbol}


def _client() -> tuple[TestClient, KillSwitchService]:
    db = AppDB(":memory:")
    audit = AuditService(db)
    svc = KillSwitchService(FakeExchange(), db, audit)
    app = create_app()
    app.dependency_overrides[ks_api.get_kill_switch] = lambda: svc
    return TestClient(app), svc


def test_activate_happy_path() -> None:
    client, _ = _client()
    resp = client.post("/killswitch/activate", json={"confirmation": "KILL"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["orders_cancelled"] == [{"oid": 1}]
    assert len(body["positions_closed"]) == 1


def test_wrong_confirmation_400() -> None:
    client, _ = _client()
    resp = client.post("/killswitch/activate", json={"confirmation": "please"})
    assert resp.status_code == 400


def test_status_reflects_state() -> None:
    client, _ = _client()
    resp = client.get("/killswitch/status")
    assert resp.json()["active"] is False
    client.post("/killswitch/activate", json={"confirmation": "KILL"})
    resp = client.get("/killswitch/status")
    body = resp.json()
    assert body["active"] is True
    assert body["last_activated"] is not None


def test_reset_requires_resume() -> None:
    client, _ = _client()
    client.post("/killswitch/activate", json={"confirmation": "KILL"})
    resp = client.post("/killswitch/reset", json={"confirmation": "no"})
    assert resp.status_code == 400
    resp = client.post("/killswitch/reset", json={"confirmation": "RESUME"})
    assert resp.status_code == 204
    assert client.get("/killswitch/status").json()["active"] is False
