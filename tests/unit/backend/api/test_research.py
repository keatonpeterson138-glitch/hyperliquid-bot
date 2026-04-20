"""API tests for /research."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from backend.api import research as research_api
from backend.main import create_app


def _bars(n: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=i) for i in range(n)]
    closes = 100 + rng.standard_normal(n).cumsum() * 0.5
    return pd.DataFrame({
        "timestamp": ts, "open": closes, "high": closes + 0.2,
        "low": closes - 0.2, "close": closes, "volume": rng.integers(100, 500, size=n).astype(float),
    })


class _FakeCatalog:
    def __init__(self, data: dict[str, pd.DataFrame]) -> None:
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def query_candles(self, symbol, interval, start, end):  # noqa: ARG002
        return self._data.get(symbol, pd.DataFrame())


def _client_with(data: dict[str, pd.DataFrame]) -> TestClient:
    catalog = _FakeCatalog(data)
    app = create_app()
    app.dependency_overrides[research_api.get_catalog_research] = lambda: catalog
    return TestClient(app)


def test_list_studies() -> None:
    c = _client_with({"BTC": _bars(100, 1)})
    resp = c.get("/research")
    assert resp.status_code == 200
    names = [s["name"] for s in resp.json()]
    assert "correlation_matrix" in names
    assert "returns_summary" in names


def test_run_returns_summary() -> None:
    c = _client_with({"BTC": _bars(500, 2)})
    resp = c.post("/research/run", json={
        "study": "returns_summary",
        "inputs": {
            "symbol": "BTC", "interval": "1h",
            "from_ts": "2024-01-01T00:00:00", "to_ts": "2024-02-01T00:00:00",
        },
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["study"] == "returns_summary"
    assert "mean" in body["columns"]


def test_run_unknown_study_404() -> None:
    c = _client_with({})
    resp = c.post("/research/run", json={"study": "bogus", "inputs": {}})
    assert resp.status_code == 404


def test_run_missing_input_400() -> None:
    c = _client_with({"BTC": _bars(100, 3)})
    resp = c.post("/research/run", json={"study": "returns_summary", "inputs": {}})
    assert resp.status_code == 400
