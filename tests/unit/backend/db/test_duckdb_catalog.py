"""Tests for the DuckDB-backed catalog + query layer.

Uses the parquet writer to seed a tmp_path data lake and then verifies
DuckDB reads partitioned files correctly, prunes by (symbol, interval)
filter, and returns empty results for an empty lake.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from backend.db.duckdb_catalog import DuckDBCatalog, list_catalog, query_candles
from backend.db.parquet_writer import append_ohlcv, append_outcomes
from backend.services.sources.base import CandleFrame


def _frame(symbol: str, interval: str, source: str, ts_list, closes) -> CandleFrame:
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


class TestDuckDBCatalog:
    def test_empty_lake_returns_empty_query(self, tmp_path) -> None:
        df = query_candles(
            "BTC",
            "1h",
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 2, tzinfo=UTC),
            data_root=tmp_path,
        )
        assert df.empty

    def test_query_single_symbol_single_source(self, tmp_path) -> None:
        ts = [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=i) for i in range(5)]
        append_ohlcv(_frame("BTC", "1h", "binance", ts, [100, 101, 102, 103, 104]), data_root=tmp_path)

        df = query_candles(
            "BTC",
            "1h",
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 2, tzinfo=UTC),
            data_root=tmp_path,
        )
        assert len(df) == 5
        assert df["close"].tolist() == [100.0, 101.0, 102.0, 103.0, 104.0]
        assert df["symbol"].iloc[0] == "BTC"

    def test_query_prunes_to_range(self, tmp_path) -> None:
        ts = [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=i) for i in range(10)]
        append_ohlcv(_frame("BTC", "1h", "binance", ts, list(range(100, 110))), data_root=tmp_path)

        df = query_candles(
            "BTC",
            "1h",
            datetime(2024, 1, 1, 2, tzinfo=UTC),
            datetime(2024, 1, 1, 5, tzinfo=UTC),
            data_root=tmp_path,
        )
        assert len(df) == 4
        assert df["close"].tolist() == [102.0, 103.0, 104.0, 105.0]

    def test_query_filters_by_source(self, tmp_path) -> None:
        ts = [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=i) for i in range(3)]
        append_ohlcv(_frame("BTC", "1h", "binance", ts, [100, 101, 102]), data_root=tmp_path)
        append_ohlcv(_frame("BTC", "1h", "coinbase", ts, [100, 101, 102]), data_root=tmp_path)

        df_all = query_candles(
            "BTC",
            "1h",
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 2, tzinfo=UTC),
            data_root=tmp_path,
        )
        df_bin = query_candles(
            "BTC",
            "1h",
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 2, tzinfo=UTC),
            data_root=tmp_path,
            source="binance",
        )
        assert len(df_all) == 6
        assert len(df_bin) == 3
        assert set(df_bin["source"].tolist()) == {"binance"}

    def test_query_spans_year_boundary(self, tmp_path) -> None:
        ts = [
            datetime(2023, 12, 31, 22, tzinfo=UTC),
            datetime(2023, 12, 31, 23, tzinfo=UTC),
            datetime(2024, 1, 1, 0, tzinfo=UTC),
            datetime(2024, 1, 1, 1, tzinfo=UTC),
        ]
        append_ohlcv(_frame("BTC", "1h", "binance", ts, [100, 101, 102, 103]), data_root=tmp_path)

        df = query_candles(
            "BTC",
            "1h",
            datetime(2023, 12, 31, tzinfo=UTC),
            datetime(2024, 1, 2, tzinfo=UTC),
            data_root=tmp_path,
        )
        assert len(df) == 4

    def test_hip3_symbol_roundtrip(self, tmp_path) -> None:
        ts = [datetime(2025, 11, 1, tzinfo=UTC) + timedelta(hours=i) for i in range(2)]
        append_ohlcv(_frame("xyz:TSLA", "1h", "hyperliquid", ts, [250, 251]), data_root=tmp_path)

        df = query_candles(
            "xyz:TSLA",
            "1h",
            datetime(2025, 11, 1, tzinfo=UTC),
            datetime(2025, 11, 2, tzinfo=UTC),
            data_root=tmp_path,
        )
        assert len(df) == 2
        assert df["symbol"].iloc[0] == "xyz:TSLA"


class TestCatalogSummary:
    def test_empty_lake_has_empty_catalog(self, tmp_path) -> None:
        summary = list_catalog(data_root=tmp_path)
        assert summary.empty

    def test_list_catalog_aggregates_per_pair(self, tmp_path) -> None:
        ts = [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=i) for i in range(3)]
        append_ohlcv(_frame("BTC", "1h", "binance", ts, [100, 101, 102]), data_root=tmp_path)
        append_ohlcv(_frame("BTC", "1h", "coinbase", ts, [100, 101, 102]), data_root=tmp_path)
        append_ohlcv(_frame("ETH", "1d", "binance", [ts[0]], [3000.0]), data_root=tmp_path)

        summary = list_catalog(data_root=tmp_path)
        assert len(summary) == 2
        btc_row = summary[summary["symbol"] == "BTC"].iloc[0]
        assert btc_row["interval"] == "1h"
        assert btc_row["bar_count"] == 6
        assert btc_row["source_count"] == 2


class TestOutcomeQuery:
    def test_empty_lake_outcomes(self, tmp_path) -> None:
        with DuckDBCatalog(tmp_path) as catalog:
            df = catalog.query_outcomes(
                "market_abc",
                datetime(2025, 11, 1, tzinfo=UTC),
                datetime(2025, 12, 1, tzinfo=UTC),
            )
        assert df.empty

    def test_query_outcomes_round_trip(self, tmp_path) -> None:
        ts = [datetime(2025, 11, 1, tzinfo=UTC) + timedelta(minutes=i) for i in range(3)]
        bars = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(ts, utc=True),
                "price": [0.42, 0.44, 0.46],
                "volume": [1000.0] * 3,
                "implied_prob": [0.42, 0.44, 0.46],
                "best_bid": [0.41, 0.43, 0.45],
                "best_ask": [0.43, 0.45, 0.47],
                "event_id": ["btc_100k"] * 3,
                "source": ["hyperliquid"] * 3,
                "ingested_at": pd.to_datetime([datetime(2026, 4, 20, tzinfo=UTC)] * 3, utc=True),
            }
        )
        append_outcomes("market_abc", bars, data_root=tmp_path)

        with DuckDBCatalog(tmp_path) as catalog:
            df = catalog.query_outcomes(
                "market_abc",
                datetime(2025, 11, 1, tzinfo=UTC),
                datetime(2025, 12, 1, tzinfo=UTC),
            )
        assert len(df) == 3
        assert df["price"].tolist() == [0.42, 0.44, 0.46]
