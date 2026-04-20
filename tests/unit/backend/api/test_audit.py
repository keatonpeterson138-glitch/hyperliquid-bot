"""API tests for /audit."""
from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api import audit as audit_api
from backend.db.app_db import AppDB
from backend.main import create_app
from backend.services.audit import AuditService


def _client() -> tuple[TestClient, AuditService]:
    db = AppDB(":memory:")
    svc = AuditService(db)
    app = create_app()
    app.dependency_overrides[audit_api.get_audit_service] = lambda: svc
    return TestClient(app), svc


def test_query_audit_returns_events() -> None:
    client, svc = _client()
    svc.log("order_placed", source="strategy", symbol="BTC", size_usd=100.0)
    svc.log("order_cancelled", source="strategy", symbol="BTC")
    resp = client.get("/audit")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert len(body["events"]) == 2


def test_filter_by_event_type_via_query_param() -> None:
    client, svc = _client()
    svc.log("order_placed", source="strategy", symbol="BTC")
    svc.log("order_cancelled", source="strategy", symbol="BTC")
    resp = client.get("/audit", params={"event_type": "order_placed"})
    assert resp.status_code == 200
    events = resp.json()["events"]
    assert len(events) == 1
    assert events[0]["event_type"] == "order_placed"


def test_csv_export() -> None:
    client, svc = _client()
    svc.log("order_placed", source="strategy", symbol="BTC", size_usd=100.0, price=50_000)
    resp = client.get("/audit.csv")
    assert resp.status_code == 200
    body = resp.text
    assert "id,ts,event_type" in body.splitlines()[0]
    assert "order_placed" in body
    assert resp.headers["content-type"].startswith("text/csv")


def test_empty_log_returns_empty_list() -> None:
    client, _ = _client()
    resp = client.get("/audit")
    assert resp.status_code == 200
    assert resp.json()["events"] == []
