"""API tests for /analog."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from backend.api import analog as analog_api
from backend.main import create_app
from backend.services.analog import AnalogEngine


def _bars(n: int) -> pd.DataFrame:
    t = np.arange(n)
    base = 100 + 5 * np.sin(2 * np.pi * t / 50) + np.random.default_rng(0).standard_normal(n) * 0.2
    ts = [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=int(i)) for i in range(n)]
    return pd.DataFrame({
        "timestamp": ts, "open": base, "high": base + 0.2,
        "low": base - 0.2, "close": base, "volume": np.full(n, 100.0),
    })


def test_post_query_returns_matches() -> None:
    bars = _bars(400)

    def cq(sym, interval, start, end):  # noqa: ARG001
        mask = (bars["timestamp"] >= start) & (bars["timestamp"] <= end)
        return bars.loc[mask]

    engine = AnalogEngine(candle_query=cq)
    app = create_app()
    app.dependency_overrides[analog_api.get_analog_engine] = lambda: engine
    c = TestClient(app)

    resp = c.post("/analog/query", json={
        "symbol": "BTC", "interval": "1h",
        "from_ts": bars["timestamp"].iloc[0].isoformat(),
        "to_ts": bars["timestamp"].iloc[280].isoformat(),
        "query_end_ts": bars["timestamp"].iloc[300].isoformat(),
        "window_len": 40, "forward_bars": 20, "top_k": 5,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert "matches" in body
    assert len(body["matches"]) > 0
    assert "p50" in body["forward_distribution"]


def test_bad_range_400() -> None:
    bars = _bars(10)

    def cq(sym, interval, start, end):  # noqa: ARG001
        return bars

    engine = AnalogEngine(candle_query=cq)
    app = create_app()
    app.dependency_overrides[analog_api.get_analog_engine] = lambda: engine
    c = TestClient(app)

    resp = c.post("/analog/query", json={
        "symbol": "BTC", "interval": "1h",
        "from_ts": "2024-01-01T00:00:00Z",
        "to_ts": "2024-01-01T05:00:00Z",
        "query_end_ts": "2024-01-01T10:00:00Z",
        "window_len": 40,
    })
    assert resp.status_code == 400
