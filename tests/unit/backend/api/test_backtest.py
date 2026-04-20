"""API tests for /backtest."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.api import backtest as backtest_api
from backend.main import create_app
from backend.services.backtest import BacktestEngine
from strategies.base import BaseStrategy, Signal, SignalType


def _bars(n: int, start_price: float = 100.0) -> pd.DataFrame:
    ts = [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=i) for i in range(n)]
    rng = np.random.default_rng(7)
    closes = start_price + rng.standard_normal(n) * 0.2 + np.arange(n) * 0.05
    closes = np.clip(closes, 1.0, None)
    return pd.DataFrame({
        "timestamp": ts,
        "open": closes,
        "high": closes + 0.1,
        "low": closes - 0.1,
        "close": closes,
        "volume": rng.integers(100, 500, size=n).astype(float),
    })


class _Scripted(BaseStrategy):
    def __init__(self, seq: list[SignalType]) -> None:
        super().__init__(name="scripted")
        self._seq = seq
        self._i = 0

    def analyze(self, df, current_position):  # noqa: ARG002
        s = self._seq[self._i % len(self._seq)]
        self._i += 1
        return Signal(signal_type=s, strength=1.0, reason="scripted")


@pytest.fixture
def client() -> TestClient:
    bars = _bars(200)

    def cq(symbol, interval, start, end):  # noqa: ARG001
        mask = (bars["timestamp"] >= start) & (bars["timestamp"] <= end)
        return bars.loc[mask]

    engine = BacktestEngine(
        cq,
        strategy_factory=lambda name, params: _Scripted([
            SignalType.LONG, *[SignalType.HOLD] * 8, SignalType.CLOSE_LONG, *[SignalType.HOLD] * 8,
        ]),
    )
    registry = backtest_api.BacktestRegistry()
    app = create_app()
    app.dependency_overrides[backtest_api.get_backtest_engine] = lambda: engine
    app.dependency_overrides[backtest_api.get_backtest_registry] = lambda: registry
    return TestClient(app)


def test_post_run_returns_metrics_and_trades(client: TestClient) -> None:
    resp = client.post("/backtest", json={
        "symbol": "BTC", "interval": "1h", "strategy": "x",
        "from_ts": "2024-01-01T00:00:00Z", "to_ts": "2024-01-09T00:00:00Z",
        "starting_cash": 10_000, "size_usd": 100, "bar_lookback": 20,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"].startswith("bt_")
    assert "trade_count" in body["metrics"]
    assert len(body["equity_curve"]) > 0


def test_get_round_trip(client: TestClient) -> None:
    created = client.post("/backtest", json={
        "symbol": "BTC", "interval": "1h", "strategy": "x",
        "from_ts": "2024-01-01T00:00:00Z", "to_ts": "2024-01-05T00:00:00Z",
        "bar_lookback": 20,
    }).json()
    resp = client.get(f"/backtest/{created['run_id']}")
    assert resp.status_code == 200
    assert resp.json()["run_id"] == created["run_id"]


def test_get_unknown_404(client: TestClient) -> None:
    assert client.get("/backtest/bt_bogus").status_code == 404


def test_sweep_returns_ranked_runs(client: TestClient) -> None:
    resp = client.post("/backtest/sweep", json={
        "base": {
            "symbol": "BTC", "interval": "1h", "strategy": "x",
            "from_ts": "2024-01-01T00:00:00Z",
            "to_ts": "2024-01-05T00:00:00Z",
            "bar_lookback": 20,
        },
        "grid": {"fast": [5, 10], "slow": [20, 40]},
        "rank_by": "total_return_pct",
    })
    assert resp.status_code == 200
    runs = resp.json()["runs"]
    assert len(runs) == 4
    vals = [r["metrics"]["total_return_pct"] for r in runs]
    assert vals == sorted(vals, reverse=True)


def test_monte_carlo_requires_existing_run(client: TestClient) -> None:
    resp = client.post("/backtest/monte-carlo", json={"run_id": "bt_bogus", "n": 10})
    assert resp.status_code == 404


def test_monte_carlo_on_real_run(client: TestClient) -> None:
    created = client.post("/backtest", json={
        "symbol": "BTC", "interval": "1h", "strategy": "x",
        "from_ts": "2024-01-01T00:00:00Z",
        "to_ts": "2024-01-09T00:00:00Z",
        "bar_lookback": 20,
    }).json()
    resp = client.post("/backtest/monte-carlo", json={"run_id": created["run_id"], "n": 50})
    assert resp.status_code == 200
    mc = resp.json()
    if created["metrics"]["trade_count"] > 0:
        assert "mc_dd_p50_pct" in mc


def test_empty_range_returns_400() -> None:
    def empty(*_a, **_k):
        return pd.DataFrame()
    engine = BacktestEngine(empty, strategy_factory=lambda n, p: _Scripted([SignalType.HOLD]))
    registry = backtest_api.BacktestRegistry()
    app = create_app()
    app.dependency_overrides[backtest_api.get_backtest_engine] = lambda: engine
    app.dependency_overrides[backtest_api.get_backtest_registry] = lambda: registry
    c = TestClient(app)
    resp = c.post("/backtest", json={
        "symbol": "NONE", "interval": "1h", "strategy": "x",
        "from_ts": "2024-01-01T00:00:00Z", "to_ts": "2024-01-02T00:00:00Z",
    })
    assert resp.status_code == 400
