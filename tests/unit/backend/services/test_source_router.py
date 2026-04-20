"""Unit tests for SourceRouter — planning + stitching + cross-validation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from backend.services.source_router import SourceRouter
from backend.services.sources.base import CANDLE_COLUMNS, CandleFrame


@dataclass
class FakeSource:
    name: str
    _supports: bool = True
    _earliest: datetime | None = None
    _frame: CandleFrame | None = None

    def supports(self, symbol: str, interval: str) -> bool:  # noqa: ARG002
        return self._supports

    def earliest_available(self, symbol: str, interval: str) -> datetime | None:  # noqa: ARG002
        return self._earliest

    def fetch_candles(self, symbol, interval, start, end):  # noqa: ARG002
        if self._frame is not None:
            return self._frame
        return _empty("BTC", "1h", self.name)


def _empty(symbol: str, interval: str, source: str) -> CandleFrame:
    cols = {c: pd.Series(dtype="float64") for c in CANDLE_COLUMNS}
    cols["timestamp"] = pd.Series(dtype="datetime64[ms, UTC]")
    cols["trades"] = pd.Series(dtype="Int64")
    cols["source"] = pd.Series(dtype="string")
    cols["ingested_at"] = pd.Series(dtype="datetime64[ms, UTC]")
    return CandleFrame(symbol=symbol, interval=interval, source=source, bars=pd.DataFrame(cols))


def _frame_with(ts_list: list[datetime], closes: list[float], source: str) -> CandleFrame:
    ts = pd.to_datetime(ts_list, utc=True)
    n = len(ts)
    bars = pd.DataFrame(
        {
            "timestamp": ts,
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [1000.0] * n,
            "trades": pd.array([pd.NA] * n, dtype="Int64"),
            "source": [source] * n,
            "ingested_at": pd.to_datetime([datetime.now(UTC)] * n, utc=True),
        }
    )
    return CandleFrame("BTC", "1h", source, bars)


class TestSourceRouterPlan:
    def test_empty_range_returns_empty_plan(self) -> None:
        router = SourceRouter([FakeSource("hyperliquid")])
        plan = router.plan(
            "BTC",
            "1h",
            datetime(2024, 1, 2, tzinfo=UTC),
            datetime(2024, 1, 1, tzinfo=UTC),
        )
        assert plan == []

    def test_single_source_covers_full_range(self) -> None:
        src = FakeSource("hyperliquid", _earliest=datetime(2020, 1, 1, tzinfo=UTC))
        router = SourceRouter([src])

        plan = router.plan(
            "BTC",
            "1h",
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 6, 1, tzinfo=UTC),
        )
        assert len(plan) == 1
        assert plan[0].source is src
        assert plan[0].start == datetime(2024, 1, 1, tzinfo=UTC)
        assert plan[0].end == datetime(2024, 6, 1, tzinfo=UTC)

    def test_stitches_across_three_sources_oldest_first(self) -> None:
        hl = FakeSource("hyperliquid", _earliest=datetime(2024, 1, 1, tzinfo=UTC))
        bn = FakeSource("binance", _earliest=datetime(2017, 8, 17, tzinfo=UTC))
        cb = FakeSource("coinbase", _earliest=datetime(2015, 7, 20, tzinfo=UTC))
        router = SourceRouter([hl, bn, cb])  # priority: hl > bn > cb

        plan = router.plan(
            "BTC",
            "1h",
            datetime(2015, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 1, tzinfo=UTC),
        )

        # Oldest-first: coinbase → binance → hyperliquid
        assert [s.source_name for s in plan] == ["coinbase", "binance", "hyperliquid"]
        # Coinbase covers from its earliest (which is > input start) to binance.earliest
        assert plan[0].start == datetime(2015, 7, 20, tzinfo=UTC)
        assert plan[0].end == datetime(2017, 8, 17, tzinfo=UTC)
        assert plan[1].start == datetime(2017, 8, 17, tzinfo=UTC)
        assert plan[1].end == datetime(2024, 1, 1, tzinfo=UTC)
        assert plan[2].start == datetime(2024, 1, 1, tzinfo=UTC)
        assert plan[2].end == datetime(2026, 1, 1, tzinfo=UTC)

    def test_skips_sources_that_dont_reach_gap(self) -> None:
        hl = FakeSource("hyperliquid", _earliest=datetime(2023, 1, 1, tzinfo=UTC))
        bn = FakeSource("binance", _earliest=datetime(2024, 1, 1, tzinfo=UTC))  # later than hl
        router = SourceRouter([hl, bn])

        plan = router.plan(
            "BTC",
            "1h",
            datetime(2022, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 1, tzinfo=UTC),
        )
        # hl takes the full range; bn has nothing to add below 2023-01-01.
        assert len(plan) == 1
        assert plan[0].source_name == "hyperliquid"

    def test_respects_input_start_clamp(self) -> None:
        hl = FakeSource("hyperliquid", _earliest=datetime(2020, 1, 1, tzinfo=UTC))
        bn = FakeSource("binance", _earliest=datetime(2017, 8, 17, tzinfo=UTC))
        router = SourceRouter([hl, bn])

        # Input start is later than binance.earliest — binance slice clamped to input start.
        plan = router.plan(
            "BTC",
            "1h",
            datetime(2019, 1, 1, tzinfo=UTC),
            datetime(2021, 1, 1, tzinfo=UTC),
        )
        assert [s.source_name for s in plan] == ["binance", "hyperliquid"]
        assert plan[0].start == datetime(2019, 1, 1, tzinfo=UTC)
        assert plan[0].end == datetime(2020, 1, 1, tzinfo=UTC)

    def test_skips_unsupporting_sources(self) -> None:
        hl = FakeSource("hyperliquid", _supports=True, _earliest=datetime(2024, 1, 1, tzinfo=UTC))
        yf = FakeSource("yfinance", _supports=False)
        router = SourceRouter([hl, yf])

        plan = router.plan(
            "BTC",
            "1h",
            datetime(2023, 1, 1, tzinfo=UTC),
            datetime(2024, 6, 1, tzinfo=UTC),
        )
        names = [s.source_name for s in plan]
        assert "yfinance" not in names

    def test_no_supporting_source_returns_empty(self) -> None:
        router = SourceRouter([FakeSource("hyperliquid", _supports=False)])
        plan = router.plan(
            "FOO",
            "1h",
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 2, 1, tzinfo=UTC),
        )
        assert plan == []

    def test_unknown_earliest_acts_as_cover_all(self) -> None:
        # Source with no earliest_available takes the full range even if
        # later-priority sources exist.
        hl = FakeSource("hyperliquid", _earliest=None)
        bn = FakeSource("binance", _earliest=datetime(2017, 8, 17, tzinfo=UTC))
        router = SourceRouter([hl, bn])

        plan = router.plan(
            "BTC",
            "1h",
            datetime(2020, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 1, tzinfo=UTC),
        )
        # Router walks the unknown-earliest primary first — it claims the whole
        # range since "unknown" means "assume covers all."
        assert len(plan) == 1
        assert plan[0].source_name == "hyperliquid"


class TestSourceRouterCrossValidate:
    def test_zero_divergence_on_identical_frames(self) -> None:
        ts = [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=i) for i in range(5)]
        closes = [100.0, 101.0, 102.0, 103.0, 104.0]
        a = FakeSource("hyperliquid", _frame=_frame_with(ts, closes, "hyperliquid"))
        b = FakeSource("binance", _frame=_frame_with(ts, closes, "binance"))
        router = SourceRouter([a, b])

        result = router.cross_validate(
            "BTC",
            "1h",
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 1, 5, tzinfo=UTC),
            source_a="hyperliquid",
            source_b="binance",
        )
        assert result.overlap_rows == 5
        assert result.divergence_max_pct == pytest.approx(0.0)
        assert not result.diverged

    def test_divergence_above_threshold_flags(self) -> None:
        ts = [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=i) for i in range(3)]
        a = FakeSource("hyperliquid", _frame=_frame_with(ts, [100, 101, 102], "hyperliquid"))
        b = FakeSource("binance", _frame=_frame_with(ts, [105, 101, 102], "binance"))  # 5% off on bar 0
        router = SourceRouter([a, b])

        result = router.cross_validate(
            "BTC",
            "1h",
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 1, 3, tzinfo=UTC),
            source_a="hyperliquid",
            source_b="binance",
            divergence_threshold_pct=1.0,
        )
        assert result.overlap_rows == 3
        assert result.divergence_max_pct > 4.0
        assert result.diverged

    def test_empty_frames_return_zero_result(self) -> None:
        a = FakeSource("hyperliquid", _frame=_empty("BTC", "1h", "hyperliquid"))
        b = FakeSource("binance", _frame=_empty("BTC", "1h", "binance"))
        router = SourceRouter([a, b])

        result = router.cross_validate(
            "BTC",
            "1h",
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 2, tzinfo=UTC),
            source_a="hyperliquid",
            source_b="binance",
        )
        assert result.overlap_rows == 0
        assert not result.diverged

    def test_unknown_source_name_raises(self) -> None:
        router = SourceRouter([FakeSource("hyperliquid")])
        with pytest.raises(KeyError):
            router.cross_validate(
                "BTC",
                "1h",
                datetime(2024, 1, 1, tzinfo=UTC),
                datetime(2024, 1, 2, tzinfo=UTC),
                source_a="hyperliquid",
                source_b="coinbase",
            )


class TestSourceRouterConstruction:
    def test_empty_sources_raises(self) -> None:
        with pytest.raises(ValueError):
            SourceRouter([])

    def test_supports_delegates_to_sources(self) -> None:
        router = SourceRouter([FakeSource("a", _supports=False), FakeSource("b", _supports=True)])
        assert router.supports("BTC", "1h")
