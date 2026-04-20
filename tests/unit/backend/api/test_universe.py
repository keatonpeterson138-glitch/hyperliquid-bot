"""API tests for /universe."""
from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api import universe as universe_api
from backend.db.app_db import AppDB
from backend.main import create_app
from backend.services.universe_manager import UniverseManager


class FakeInfo:
    def meta(self, dex=""):
        if dex == "":
            return {"universe": [{"name": "BTC"}, {"name": "ETH"}]}
        if dex == "xyz":
            return {"universe": [{"name": "TSLA"}]}
        return {"universe": []}


def _client() -> tuple[TestClient, UniverseManager]:
    db = AppDB(":memory:")
    um = UniverseManager(db, info=FakeInfo(), hip3_dexes=("xyz", "cash"))
    app = create_app()
    app.dependency_overrides[universe_api.get_universe_manager] = lambda: um
    return TestClient(app), um


def test_refresh_then_list() -> None:
    client, um = _client()
    # Refresh populates.
    resp = client.post("/universe/refresh")
    assert resp.status_code == 200
    assert resp.json()["markets_added"] == 3

    # List
    resp = client.get("/universe")
    assert resp.status_code == 200
    markets = resp.json()["markets"]
    assert len(markets) == 3


def test_get_market_by_id() -> None:
    client, um = _client()
    um.refresh()
    resp = client.get("/universe/perp:BTC")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "perp:BTC"


def test_unknown_market_returns_404() -> None:
    client, _ = _client()
    resp = client.get("/universe/perp:DOES_NOT_EXIST")
    assert resp.status_code == 404


def test_tag_and_untag() -> None:
    client, um = _client()
    um.refresh()
    resp = client.post("/universe/perp:BTC/tag", json={"tag": "train"})
    assert resp.status_code == 204
    btc = client.get("/universe/perp:BTC").json()
    assert "train" in btc["tags"]

    resp = client.request(
        "DELETE", "/universe/perp:BTC/tag", json={"tag": "train"}
    )
    assert resp.status_code == 204
    btc = client.get("/universe/perp:BTC").json()
    assert btc["tags"] == []


def test_tag_unknown_market_404() -> None:
    client, _ = _client()
    resp = client.post("/universe/perp:BOGUS/tag", json={"tag": "x"})
    assert resp.status_code == 404


def test_markets_by_tag() -> None:
    client, um = _client()
    um.refresh()
    client.post("/universe/perp:BTC/tag", json={"tag": "trade"})
    client.post("/universe/perp:ETH/tag", json={"tag": "trade"})
    resp = client.get("/universe/tag/trade")
    assert resp.status_code == 200
    symbols = {m["id"] for m in resp.json()["markets"]}
    assert symbols == {"perp:BTC", "perp:ETH"}
