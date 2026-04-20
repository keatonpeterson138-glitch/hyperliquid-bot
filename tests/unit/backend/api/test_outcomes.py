"""API tests for /outcomes/{market_id}/tape."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
from fastapi.testclient import TestClient

from backend.api import outcomes as outcomes_api
from backend.db.duckdb_catalog import DuckDBCatalog
from backend.db.parquet_writer import append_outcomes
from backend.main import create_app


def _seed(tmp_path):
    ts = [datetime(2025, 11, 1, tzinfo=UTC) + timedelta(minutes=i) for i in range(3)]
    bars = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(ts, utc=True),
            "price": [0.42, 0.44, 0.46],
            "volume": [1000.0, 500.0, 750.0],
            "implied_prob": [0.42, 0.44, 0.46],
            "best_bid": [0.41, 0.43, 0.45],
            "best_ask": [0.43, 0.45, 0.47],
            "event_id": ["btc_100k"] * 3,
            "source": ["hyperliquid-outcomes"] * 3,
            "ingested_at": pd.to_datetime([datetime(2026, 4, 20, tzinfo=UTC)] * 3, utc=True),
        }
    )
    append_outcomes("market_abc", bars, data_root=tmp_path)


def _client(tmp_path) -> TestClient:
    app = create_app()
    app.dependency_overrides[outcomes_api.get_catalog] = lambda: DuckDBCatalog(tmp_path)
    return TestClient(app)


def test_returns_ticks_in_range(tmp_path) -> None:
    _seed(tmp_path)
    client = _client(tmp_path)
    resp = client.get(
        "/outcomes/market_abc/tape",
        params={"from": "2025-11-01T00:00:00Z", "to": "2025-12-01T00:00:00Z"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["market_id"] == "market_abc"
    assert body["tick_count"] == 3
    assert [t["price"] for t in body["ticks"]] == [0.42, 0.44, 0.46]


def test_empty_for_unknown_market(tmp_path) -> None:
    _seed(tmp_path)
    client = _client(tmp_path)
    resp = client.get(
        "/outcomes/does_not_exist/tape",
        params={"from": "2025-11-01T00:00:00Z"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["tick_count"] == 0
    assert body["ticks"] == []


def test_to_defaults_to_now(tmp_path) -> None:
    _seed(tmp_path)
    client = _client(tmp_path)
    resp = client.get(
        "/outcomes/market_abc/tape",
        params={"from": "2025-11-01T00:00:00Z"},
    )
    assert resp.status_code == 200
    assert resp.json()["tick_count"] == 3
