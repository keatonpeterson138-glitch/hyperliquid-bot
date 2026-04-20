"""API tests for /candles, /catalog, /backfill."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.api import candles as candles_api
from backend.db.parquet_writer import append_ohlcv
from backend.main import create_app
from backend.services.backfill_service import BackfillService
from backend.services.source_router import SourceRouter
from backend.services.sources.base import CANDLE_COLUMNS, CandleFrame


def _frame(symbol, interval, source, ts_list, closes) -> CandleFrame:
    bars = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(ts_list, utc=True),
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [1000.0] * len(closes),
            "trades": pd.array([pd.NA] * len(closes), dtype="Int64"),
            "source": [source] * len(closes),
            "ingested_at": pd.to_datetime([datetime(2026, 4, 20, tzinfo=UTC)] * len(closes), utc=True),
        }
    )
    return CandleFrame(symbol, interval, source, bars)


@pytest.fixture
def seeded_client(tmp_path):
    """App with a catalog pointed at a pre-seeded tmp_path lake."""
    from backend.db.duckdb_catalog import DuckDBCatalog

    ts = [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=i) for i in range(5)]
    append_ohlcv(_frame("BTC", "1h", "binance", ts, [100, 101, 102, 103, 104]), data_root=tmp_path)

    app = create_app()
    app.dependency_overrides[candles_api.get_catalog] = lambda: DuckDBCatalog(tmp_path)
    return TestClient(app), tmp_path


class TestCandlesEndpoint:
    def test_returns_bars_in_range(self, seeded_client) -> None:
        client, _ = seeded_client
        resp = client.get(
            "/candles",
            params={
                "symbol": "BTC",
                "interval": "1h",
                "from": "2024-01-01T00:00:00Z",
                "to": "2024-01-01T05:00:00Z",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["symbol"] == "BTC"
        assert body["interval"] == "1h"
        assert body["bar_count"] == 5
        assert len(body["bars"]) == 5
        assert body["source_breakdown"] == {"binance": 5}
        assert body["bars"][0]["close"] == 100.0

    def test_returns_empty_outside_range(self, seeded_client) -> None:
        client, _ = seeded_client
        resp = client.get(
            "/candles",
            params={
                "symbol": "BTC",
                "interval": "1h",
                "from": "2030-01-01T00:00:00Z",
                "to": "2030-02-01T00:00:00Z",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["bar_count"] == 0
        assert body["bars"] == []

    def test_bad_interval_rejected_at_validation(self, seeded_client) -> None:
        client, _ = seeded_client
        resp = client.get(
            "/candles",
            params={
                "symbol": "BTC",
                "interval": "3m",
                "from": "2024-01-01T00:00:00Z",
            },
        )
        assert resp.status_code == 422


class TestCatalogEndpoint:
    def test_returns_entries_for_seeded_pairs(self, seeded_client, tmp_path) -> None:
        client, root = seeded_client
        ts = [datetime(2024, 1, 1, tzinfo=UTC)]
        append_ohlcv(_frame("ETH", "1d", "binance", ts, [3000.0]), data_root=root)

        resp = client.get("/catalog")
        assert resp.status_code == 200
        entries = {(e["symbol"], e["interval"]): e for e in resp.json()["entries"]}
        assert ("BTC", "1h") in entries
        assert ("ETH", "1d") in entries
        assert entries[("BTC", "1h")]["bar_count"] == 5

    def test_empty_lake_returns_empty_entries(self, tmp_path) -> None:
        from backend.db.duckdb_catalog import DuckDBCatalog

        app = create_app()
        app.dependency_overrides[candles_api.get_catalog] = lambda: DuckDBCatalog(tmp_path)
        client = TestClient(app)

        resp = client.get("/catalog")
        assert resp.status_code == 200
        assert resp.json()["entries"] == []


@dataclass
class _FakeSource:
    name: str = "hyperliquid"
    frame: CandleFrame | None = None
    calls: list[tuple] = field(default_factory=list)

    def supports(self, symbol, interval):  # noqa: ARG002
        return True

    def earliest_available(self, symbol, interval):  # noqa: ARG002
        return None

    def fetch_candles(self, symbol, interval, start, end):
        self.calls.append((symbol, interval, start, end))
        if self.frame is None:
            return _empty_frame(symbol, interval, self.name)
        return self.frame


def _empty_frame(symbol, interval, source) -> CandleFrame:
    bars = pd.DataFrame({c: [] for c in CANDLE_COLUMNS})
    bars["timestamp"] = pd.to_datetime(bars["timestamp"], utc=True)
    bars["ingested_at"] = pd.to_datetime(bars["ingested_at"], utc=True)
    bars["trades"] = pd.Series(dtype="Int64")
    bars["source"] = pd.Series(dtype="string")
    return CandleFrame(symbol, interval, source, bars)


class TestBackfillEndpoint:
    def test_runs_with_injected_service(self, tmp_path) -> None:
        ts = [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=i) for i in range(3)]
        src = _FakeSource(frame=_frame("BTC", "1h", "hyperliquid", ts, [100, 101, 102]))
        service = BackfillService(SourceRouter([src]), data_root=tmp_path)

        app = create_app()
        app.dependency_overrides[candles_api.get_backfill_service] = lambda: service
        client = TestClient(app)

        resp = client.post(
            "/backfill",
            json={
                "symbol": "BTC",
                "interval": "1h",
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-01-01T03:00:00Z",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["symbol"] == "BTC"
        assert body["rows_written"] == 3
        assert body["sources_used"] == ["hyperliquid"]
        assert body["errors"] == []

    def test_bad_interval_rejected(self, tmp_path) -> None:
        # Pydantic rejects bad intervals before touching the service; supply
        # a harmless stub to prove validation runs first regardless of deps.
        stub_service = BackfillService(
            SourceRouter([_FakeSource(frame=None)]), data_root=tmp_path
        )
        app = create_app()
        app.dependency_overrides[candles_api.get_backfill_service] = lambda: stub_service
        client = TestClient(app)
        resp = client.post(
            "/backfill",
            json={
                "symbol": "BTC",
                "interval": "3m",  # rejected
                "start": "2024-01-01T00:00:00Z",
            },
        )
        assert resp.status_code == 422

    def test_service_error_surfaces_502_when_not_allow_partial(self, tmp_path) -> None:
        class BadSource:
            name = "hyperliquid"

            def supports(self, symbol, interval):  # noqa: ARG002
                return True

            def earliest_available(self, symbol, interval):  # noqa: ARG002
                return None

            def fetch_candles(self, symbol, interval, start, end):
                raise RuntimeError("upstream dead")

        service = BackfillService(SourceRouter([BadSource()]), data_root=tmp_path)
        app = create_app()
        app.dependency_overrides[candles_api.get_backfill_service] = lambda: service
        client = TestClient(app)

        resp = client.post(
            "/backfill",
            json={
                "symbol": "BTC",
                "interval": "1h",
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-01-01T03:00:00Z",
                "allow_partial": False,
            },
        )
        assert resp.status_code == 502
