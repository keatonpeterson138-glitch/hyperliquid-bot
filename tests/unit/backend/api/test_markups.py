"""API tests for /markups — chart drawings CRUD."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api import markups as markups_api
from backend.db.app_db import AppDB
from backend.main import create_app
from backend.services.markup_store import MarkupStore


@pytest.fixture
def client() -> TestClient:
    db = AppDB(":memory:")
    store = MarkupStore(db)
    app = create_app()
    app.dependency_overrides[markups_api.get_markup_store] = lambda: store
    return TestClient(app)


def test_create_then_list(client: TestClient) -> None:
    resp = client.post(
        "/markups",
        json={
            "symbol": "BTC",
            "interval": "1h",
            "tool_id": "horizontal_line",
            "payload": {"price": 68000},
        },
    )
    assert resp.status_code == 200
    created = resp.json()
    assert created["id"].startswith("markup_")
    assert created["tool_id"] == "horizontal_line"
    assert created["payload"] == {"price": 68000}
    assert created["state"] == "draft"

    resp = client.get("/markups")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_list_filters_by_symbol_and_interval(client: TestClient) -> None:
    for sym, iv in [("BTC", "1h"), ("BTC", "4h"), ("ETH", "1h")]:
        client.post(
            "/markups",
            json={"symbol": sym, "interval": iv, "tool_id": "trendline", "payload": {}},
        )

    assert len(client.get("/markups").json()) == 3
    assert len(client.get("/markups", params={"symbol": "BTC"}).json()) == 2
    assert (
        len(client.get("/markups", params={"symbol": "BTC", "interval": "1h"}).json())
        == 1
    )


def test_patch_updates_payload_and_state(client: TestClient) -> None:
    created = client.post(
        "/markups",
        json={
            "symbol": "BTC",
            "tool_id": "horizontal_line",
            "payload": {"price": 68000},
        },
    ).json()

    resp = client.patch(
        f"/markups/{created['id']}",
        json={"payload": {"price": 70000}, "state": "active", "locked": True},
    )
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["payload"] == {"price": 70000}
    assert updated["state"] == "active"
    assert updated["locked"] is True


def test_patch_unknown_id_returns_404(client: TestClient) -> None:
    resp = client.patch("/markups/markup_bogus", json={"state": "active"})
    assert resp.status_code == 404


def test_delete_removes_row(client: TestClient) -> None:
    created = client.post(
        "/markups",
        json={"symbol": "BTC", "tool_id": "horizontal_line", "payload": {"price": 1}},
    ).json()

    resp = client.delete(f"/markups/{created['id']}")
    assert resp.status_code == 204
    assert client.get("/markups").json() == []


def test_503_when_store_not_wired() -> None:
    app = create_app()
    client = TestClient(app)
    resp = client.get("/markups")
    assert resp.status_code == 503
