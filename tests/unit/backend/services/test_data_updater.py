"""Tests for DataUpdater — inject fake source + tmp_path lake."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pandas as pd

from backend.db.parquet_reader import latest_timestamp
from backend.db.parquet_writer import append_ohlcv
from backend.services.data_updater import DataUpdater
from backend.services.sources.base import CANDLE_COLUMNS, CandleFrame


@dataclass
class FakeSource:
    name: str = "hyperliquid"
    frames_to_return: list[CandleFrame] = field(default_factory=list)
    call_log: list[tuple[str, str, datetime, datetime]] = field(default_factory=list)

    def supports(self, symbol: str, interval: str) -> bool:  # noqa: ARG002
        return True

    def earliest_available(self, symbol: str, interval: str) -> datetime | None:  # noqa: ARG002
        return None

    def fetch_candles(self, symbol, interval, start, end):
        self.call_log.append((symbol, interval, start, end))
        if self.frames_to_return:
            return self.frames_to_return.pop(0)
        return _empty_frame(symbol, interval, self.name)


def _frame_with(symbol, interval, source, ts_list, closes) -> CandleFrame:
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


def _empty_frame(symbol, interval, source) -> CandleFrame:
    bars = pd.DataFrame({c: [] for c in CANDLE_COLUMNS})
    bars["timestamp"] = pd.to_datetime(bars["timestamp"], utc=True)
    bars["ingested_at"] = pd.to_datetime(bars["ingested_at"], utc=True)
    bars["trades"] = pd.Series(dtype="Int64")
    bars["source"] = pd.Series(dtype="string")
    return CandleFrame(symbol, interval, source, bars)


class TestDataUpdater:
    def test_first_run_pulls_back_lookback_window(self, tmp_path) -> None:
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
        src = FakeSource()
        src.frames_to_return = [_empty_frame("BTC", "1h", "hyperliquid")]
        updater = DataUpdater(symbol="BTC", interval="1h", source=src, data_root=tmp_path)

        updater.tick(now=now)
        # One call made, starting 2 days before `now`.
        assert len(src.call_log) == 1
        symbol, interval, start, end = src.call_log[0]
        assert end == now
        assert (now - start) >= timedelta(days=2) - timedelta(minutes=1)

    def test_subsequent_tick_starts_after_latest_stored(self, tmp_path) -> None:
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
        # Seed the lake with some bars.
        existing_ts = [now - timedelta(hours=i) for i in range(5, 0, -1)]
        existing = _frame_with("BTC", "1h", "binance", existing_ts, [100, 101, 102, 103, 104])
        append_ohlcv(existing, data_root=tmp_path)

        # New tick brings in the next bar.
        new_ts = [now - timedelta(minutes=5)]
        src = FakeSource()
        src.frames_to_return = [_frame_with("BTC", "1h", "hyperliquid", new_ts, [105.0])]
        updater = DataUpdater(symbol="BTC", interval="1h", source=src, data_root=tmp_path)

        n = updater.tick(now=now)
        assert n > 0
        symbol, interval, start, end = src.call_log[0]
        # Start is roughly latest_stored + 1h.
        assert start >= now - timedelta(hours=1, minutes=10)
        assert start <= now
        # Latest now reflects the new bar.
        latest = latest_timestamp("BTC", "1h", data_root=tmp_path)
        assert latest is not None
        assert latest >= new_ts[0] - timedelta(seconds=1)

    def test_noop_when_already_current(self, tmp_path) -> None:
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
        existing = _frame_with("BTC", "1h", "binance", [now], [100.0])
        append_ohlcv(existing, data_root=tmp_path)

        src = FakeSource()
        updater = DataUpdater(symbol="BTC", interval="1h", source=src, data_root=tmp_path)
        n = updater.tick(now=now)
        # start = latest + 1h > now → skip.
        assert n == 0
        assert src.call_log == []

    def test_on_new_bars_callback_fires(self, tmp_path) -> None:
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
        src = FakeSource()
        new_ts = [now - timedelta(minutes=30)]
        src.frames_to_return = [_frame_with("BTC", "1h", "hyperliquid", new_ts, [105.0])]

        callback_frames: list[CandleFrame] = []
        updater = DataUpdater(
            symbol="BTC",
            interval="1h",
            source=src,
            data_root=tmp_path,
            on_new_bars=callback_frames.append,
        )
        updater.tick(now=now)
        assert len(callback_frames) == 1
        assert callback_frames[0].bars["close"].tolist() == [105.0]

    def test_exception_in_fetch_returns_zero_and_logs(self, tmp_path) -> None:
        class BadSource:
            name = "hyperliquid"

            def supports(self, symbol, interval):  # noqa: ARG002
                return True

            def earliest_available(self, symbol, interval):  # noqa: ARG002
                return None

            def fetch_candles(self, symbol, interval, start, end):
                raise RuntimeError("simulated")

        updater = DataUpdater(
            symbol="BTC",
            interval="1h",
            source=BadSource(),
            data_root=tmp_path,
        )
        n = updater.tick(now=datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC))
        assert n == 0

    def test_callback_exception_does_not_propagate(self, tmp_path) -> None:
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
        src = FakeSource()
        src.frames_to_return = [
            _frame_with("BTC", "1h", "hyperliquid", [now - timedelta(minutes=30)], [105.0])
        ]

        def bad_callback(_frame):
            raise RuntimeError("callback explodes")

        updater = DataUpdater(
            symbol="BTC",
            interval="1h",
            source=src,
            data_root=tmp_path,
            on_new_bars=bad_callback,
        )
        # Must not raise — tick returns rows written, callback error is logged.
        n = updater.tick(now=now)
        assert n > 0
