"""Round-trip + dedupe tests for the Parquet writer/reader."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from backend.db.parquet_reader import latest_timestamp, partition_exists, read_ohlcv
from backend.db.parquet_writer import append_ohlcv, append_outcomes
from backend.db.paths import ohlcv_partition_path, outcome_partition_path
from backend.services.sources.base import CANDLE_COLUMNS, CandleFrame


def _candle_frame(
    symbol: str,
    interval: str,
    source: str,
    ts_list: list[datetime],
    closes: list[float],
    *,
    ingested_at: datetime | None = None,
) -> CandleFrame:
    assert len(ts_list) == len(closes)
    ing = ingested_at or datetime(2026, 4, 20, tzinfo=UTC)
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
            "ingested_at": pd.to_datetime([ing] * len(closes), utc=True),
        }
    )
    return CandleFrame(symbol=symbol, interval=interval, source=source, bars=bars)


class TestAppendOhlcv:
    def test_empty_frame_writes_nothing(self, tmp_path) -> None:
        bars = pd.DataFrame({c: [] for c in CANDLE_COLUMNS})
        bars["timestamp"] = pd.to_datetime(bars["timestamp"], utc=True)
        bars["ingested_at"] = pd.to_datetime(bars["ingested_at"], utc=True)
        bars["trades"] = pd.Series(dtype="Int64")
        bars["source"] = pd.Series(dtype="string")
        frame = CandleFrame("BTC", "1h", "binance", bars)
        total = append_ohlcv(frame, data_root=tmp_path)
        assert total == 0

    def test_round_trip_single_year(self, tmp_path) -> None:
        ts = [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=i) for i in range(3)]
        frame = _candle_frame("BTC", "1h", "binance", ts, [100, 101, 102])
        written = append_ohlcv(frame, data_root=tmp_path)
        assert written == 3
        assert partition_exists("BTC", "1h", 2024, data_root=tmp_path)

        read = read_ohlcv(
            "BTC",
            "1h",
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 2, tzinfo=UTC),
            data_root=tmp_path,
        )
        assert len(read) == 3
        assert read["close"].tolist() == [100.0, 101.0, 102.0]

    def test_append_extends_partition(self, tmp_path) -> None:
        ts1 = [datetime(2024, 1, 1, i, tzinfo=UTC) for i in range(3)]
        ts2 = [datetime(2024, 1, 1, i, tzinfo=UTC) for i in range(3, 6)]
        append_ohlcv(_candle_frame("BTC", "1h", "binance", ts1, [100, 101, 102]), data_root=tmp_path)
        append_ohlcv(_candle_frame("BTC", "1h", "binance", ts2, [103, 104, 105]), data_root=tmp_path)

        read = read_ohlcv(
            "BTC",
            "1h",
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 2, tzinfo=UTC),
            data_root=tmp_path,
        )
        assert len(read) == 6
        assert read["close"].tolist() == [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]

    def test_dedupe_on_timestamp_plus_source(self, tmp_path) -> None:
        ts = [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=i) for i in range(3)]
        append_ohlcv(
            _candle_frame("BTC", "1h", "binance", ts, [100, 101, 102]), data_root=tmp_path
        )
        # Re-ingest same timestamps, same source → no duplicate rows.
        append_ohlcv(
            _candle_frame(
                "BTC",
                "1h",
                "binance",
                ts,
                [999, 999, 999],
                ingested_at=datetime(2026, 5, 1, tzinfo=UTC),
            ),
            data_root=tmp_path,
        )
        read = read_ohlcv(
            "BTC",
            "1h",
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 2, tzinfo=UTC),
            data_root=tmp_path,
        )
        assert len(read) == 3
        # Last-write-wins on same (ts, source): newer ingested_at overwrites values.
        assert read["close"].tolist() == [999.0, 999.0, 999.0]

    def test_different_sources_coexist_on_same_timestamp(self, tmp_path) -> None:
        ts = [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=i) for i in range(2)]
        append_ohlcv(_candle_frame("BTC", "1h", "binance", ts, [100, 101]), data_root=tmp_path)
        append_ohlcv(_candle_frame("BTC", "1h", "coinbase", ts, [100, 101]), data_root=tmp_path)

        read = read_ohlcv(
            "BTC",
            "1h",
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 2, tzinfo=UTC),
            data_root=tmp_path,
        )
        assert len(read) == 4
        assert set(read["source"].tolist()) == {"binance", "coinbase"}

    def test_year_boundary_splits_partitions(self, tmp_path) -> None:
        ts = [
            datetime(2023, 12, 31, 23, tzinfo=UTC),
            datetime(2024, 1, 1, 0, tzinfo=UTC),
            datetime(2024, 1, 1, 1, tzinfo=UTC),
        ]
        append_ohlcv(_candle_frame("BTC", "1h", "binance", ts, [100, 101, 102]), data_root=tmp_path)

        assert partition_exists("BTC", "1h", 2023, data_root=tmp_path)
        assert partition_exists("BTC", "1h", 2024, data_root=tmp_path)

    def test_hip3_symbol_sanitized_in_path(self, tmp_path) -> None:
        ts = [datetime(2025, 11, 1, tzinfo=UTC)]
        append_ohlcv(
            _candle_frame("xyz:TSLA", "1h", "hyperliquid", ts, [250.0]), data_root=tmp_path
        )
        # Path component replaces ':' with '__' for cross-platform safety.
        path = ohlcv_partition_path(tmp_path, "xyz:TSLA", "1h", 2025)
        assert "symbol=xyz__TSLA" in str(path)
        assert path.exists()


class TestLatestTimestamp:
    def test_returns_none_for_empty_lake(self, tmp_path) -> None:
        assert latest_timestamp("BTC", "1h", data_root=tmp_path) is None

    def test_returns_newest_across_years(self, tmp_path) -> None:
        append_ohlcv(
            _candle_frame(
                "BTC",
                "1h",
                "binance",
                [datetime(2023, 12, 31, tzinfo=UTC)],
                [100.0],
            ),
            data_root=tmp_path,
        )
        append_ohlcv(
            _candle_frame(
                "BTC",
                "1h",
                "binance",
                [datetime(2024, 6, 15, tzinfo=UTC)],
                [105.0],
            ),
            data_root=tmp_path,
        )
        ts = latest_timestamp("BTC", "1h", data_root=tmp_path)
        assert ts is not None
        assert ts.year == 2024
        assert ts.month == 6


class TestAppendOutcomes:
    def test_round_trip_outcome_tape(self, tmp_path) -> None:
        ts = [datetime(2025, 11, 1, tzinfo=UTC) + timedelta(minutes=i) for i in range(3)]
        bars = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(ts, utc=True),
                "price": [0.42, 0.44, 0.46],
                "volume": [1000.0] * 3,
                "implied_prob": [0.42, 0.44, 0.46],
                "best_bid": [0.41, 0.43, 0.45],
                "best_ask": [0.43, 0.45, 0.47],
                "event_id": ["btc_100k_eoy"] * 3,
                "source": ["hyperliquid"] * 3,
                "ingested_at": pd.to_datetime([datetime.now(UTC)] * 3, utc=True),
            }
        )
        written = append_outcomes("market_abc", bars, data_root=tmp_path)
        assert written == 3
        assert outcome_partition_path(tmp_path, "market_abc", 2025).exists()


@pytest.fixture
def sample_frame() -> CandleFrame:
    ts = [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=i) for i in range(5)]
    return _candle_frame("BTC", "1h", "binance", ts, [100.0, 101.0, 102.0, 103.0, 104.0])


def test_read_ohlcv_filters_outside_range(tmp_path, sample_frame) -> None:
    append_ohlcv(sample_frame, data_root=tmp_path)
    # Ask for a window narrower than what was written.
    read = read_ohlcv(
        "BTC",
        "1h",
        datetime(2024, 1, 1, 1, tzinfo=UTC),
        datetime(2024, 1, 1, 3, tzinfo=UTC),
        data_root=tmp_path,
    )
    assert len(read) == 3
    assert read["close"].tolist() == [101.0, 102.0, 103.0]
