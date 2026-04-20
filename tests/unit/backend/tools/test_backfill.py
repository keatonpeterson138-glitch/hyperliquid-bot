"""Tests for the backfill CLI.

Injects a fake router + append_fn so tests don't touch the network or
the file system.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from backend.services.source_router import SourceRouter
from backend.services.sources.base import CANDLE_COLUMNS, CandleFrame
from backend.tools.backfill import BackfillArgs, _parse_args, main, run


@dataclass
class RecordingSource:
    name: str
    _frame: CandleFrame
    call_log: list[tuple[str, str, datetime, datetime]]

    def supports(self, symbol: str, interval: str) -> bool:  # noqa: ARG002
        return True

    def earliest_available(self, symbol: str, interval: str) -> datetime | None:  # noqa: ARG002
        return None

    def fetch_candles(self, symbol, interval, start, end):
        self.call_log.append((symbol, interval, start, end))
        return self._frame


def _frame_with(symbol, interval, source, n: int) -> CandleFrame:
    bars = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [datetime(2024, 1, 1, tzinfo=UTC).replace(hour=i) for i in range(n)],
                utc=True,
            ),
            "open": [100.0 + i for i in range(n)],
            "high": [101.0 + i for i in range(n)],
            "low": [99.0 + i for i in range(n)],
            "close": [100.5 + i for i in range(n)],
            "volume": [1000.0] * n,
            "trades": pd.array([pd.NA] * n, dtype="Int64"),
            "source": [source] * n,
            "ingested_at": pd.to_datetime([datetime.now(UTC)] * n, utc=True),
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


def _args(tmp_path: Path, **overrides) -> BackfillArgs:
    defaults = dict(
        symbol="BTC",
        interval="1h",
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 1, 2, tzinfo=UTC),
        depth="target",
        data_root=tmp_path,
        source=None,
        allow_partial=False,
        testnet=False,
    )
    defaults.update(overrides)
    return BackfillArgs(**defaults)


class TestBackfillRun:
    def test_empty_plan_is_noop(self, tmp_path) -> None:
        def factory() -> SourceRouter:
            src = RecordingSource(
                "hyperliquid", _empty_frame("BTC", "1h", "hyperliquid"), call_log=[]
            )
            router = SourceRouter([src])
            # Force empty plan by asking for zero-length range
            return router

        log: list[str] = []
        # zero-length range triggers empty plan inside run()
        args = _args(tmp_path, start=datetime(2024, 1, 2, tzinfo=UTC))
        result = run(args, router_factory=factory, progress_fn=log.append)
        assert result == 0

    def test_walks_plan_and_calls_append_per_slice(self, tmp_path) -> None:
        src_a = RecordingSource(
            "binance", _frame_with("BTC", "1h", "binance", 3), call_log=[]
        )
        src_b = RecordingSource(
            "hyperliquid", _frame_with("BTC", "1h", "hyperliquid", 2), call_log=[]
        )

        def factory():
            return SourceRouter([src_b, src_a])  # hyperliquid first-priority

        append_log: list[tuple[CandleFrame, Path]] = []

        def fake_append(frame: CandleFrame, data_root: Path) -> int:
            append_log.append((frame, data_root))
            return len(frame.bars)

        args = _args(tmp_path)
        result = run(args, router_factory=factory, append_fn=fake_append)
        assert result == 5
        assert len(append_log) == 2
        assert append_log[0][1] == tmp_path
        assert len(src_a.call_log) == 1
        assert len(src_b.call_log) == 1

    def test_empty_frames_dont_call_append(self, tmp_path) -> None:
        src = RecordingSource("binance", _empty_frame("BTC", "1h", "binance"), call_log=[])

        append_log = []

        def fake_append(frame, data_root):
            append_log.append(frame)
            return 0

        args = _args(tmp_path)
        result = run(args, router_factory=lambda: SourceRouter([src]), append_fn=fake_append)
        assert result == 0
        assert append_log == []

    def test_exception_in_source_returns_negative_when_not_allow_partial(self, tmp_path) -> None:
        class BadSource:
            name = "binance"

            def supports(self, symbol, interval):  # noqa: ARG002
                return True

            def earliest_available(self, symbol, interval):  # noqa: ARG002
                return None

            def fetch_candles(self, symbol, interval, start, end):
                raise RuntimeError("simulated network glitch")

        args = _args(tmp_path)
        result = run(
            args,
            router_factory=lambda: SourceRouter([BadSource()]),
            append_fn=lambda f, p: 0,
        )
        assert result == -1

    def test_exception_tolerated_with_allow_partial(self, tmp_path) -> None:
        class BadSource:
            name = "binance"

            def supports(self, symbol, interval):  # noqa: ARG002
                return True

            def earliest_available(self, symbol, interval):  # noqa: ARG002
                return None

            def fetch_candles(self, symbol, interval, start, end):
                raise RuntimeError("simulated network glitch")

        args = _args(tmp_path, allow_partial=True)
        result = run(
            args,
            router_factory=lambda: SourceRouter([BadSource()]),
            append_fn=lambda f, p: 0,
        )
        assert result == 0


class TestArgParsing:
    def test_parses_required_args(self) -> None:
        args, verbose = _parse_args(
            [
                "--symbol",
                "BTC",
                "--interval",
                "1h",
                "--from",
                "2024-01-01",
                "--to",
                "2024-02-01",
            ]
        )
        assert args.symbol == "BTC"
        assert args.interval == "1h"
        assert args.start == datetime(2024, 1, 1, tzinfo=UTC)
        assert args.end == datetime(2024, 2, 1, tzinfo=UTC)
        assert not verbose

    def test_defaults_end_to_now(self) -> None:
        args, _ = _parse_args(
            ["--symbol", "BTC", "--interval", "1h", "--from", "2024-01-01"]
        )
        # "end" is ~now; can't assert exact, just that it's after start.
        assert args.end > args.start

    def test_invalid_range_rejected(self) -> None:
        with pytest.raises(SystemExit):
            _parse_args(
                [
                    "--symbol",
                    "BTC",
                    "--interval",
                    "1h",
                    "--from",
                    "2024-02-01",
                    "--to",
                    "2024-01-01",
                ]
            )

    def test_invalid_interval_rejected(self) -> None:
        with pytest.raises(SystemExit):
            _parse_args(["--symbol", "BTC", "--interval", "3m", "--from", "2024-01-01"])


class TestMainEntrypoint:
    def test_main_returns_zero_on_success(self, tmp_path, monkeypatch) -> None:
        # Point data-root at tmp_path via argv + monkeypatch the router so no
        # network is hit.
        src = RecordingSource(
            "binance", _frame_with("BTC", "1h", "binance", 3), call_log=[]
        )
        monkeypatch.setattr(
            "backend.tools.backfill.build_default_router",
            lambda **_kw: SourceRouter([src]),
        )
        code = main(
            [
                "--symbol",
                "BTC",
                "--interval",
                "1h",
                "--from",
                "2024-01-01",
                "--to",
                "2024-01-02",
                "--data-root",
                str(tmp_path),
            ]
        )
        assert code == 0
