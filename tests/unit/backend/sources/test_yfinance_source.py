"""Unit tests for YFinanceSource — no yfinance actually called.

Inject a ``download_fn`` that returns a canned DataFrame shaped like
``yfinance.download``'s output.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from backend.services.sources.base import CANDLE_COLUMNS
from backend.services.sources.hip3_map import HIP3_TO_YFINANCE, yfinance_ticker_for
from backend.services.sources.yfinance_source import YFinanceSource


def _yf_sample_df() -> pd.DataFrame:
    idx = pd.to_datetime(
        [
            "2024-01-01 00:00:00",
            "2024-01-01 01:00:00",
            "2024-01-01 02:00:00",
        ]
    ).tz_localize("UTC")
    return pd.DataFrame(
        {
            "Open": [100.0, 101.0, 102.0],
            "High": [101.5, 102.5, 103.5],
            "Low": [99.5, 100.5, 101.5],
            "Close": [101.0, 102.0, 103.0],
            "Adj Close": [101.0, 102.0, 103.0],
            "Volume": [100_000, 110_000, 120_000],
        },
        index=idx,
    )


class TestYFinanceSource:
    def test_supports_hip3_stocks(self) -> None:
        src = YFinanceSource()
        assert src.supports("xyz:TSLA", "1d")
        assert src.supports("xyz:NVDA", "1h")
        assert src.supports("cash:GOLD", "1d")

    def test_supports_bare_equity_ticker(self) -> None:
        src = YFinanceSource()
        assert src.supports("SPY", "1d")

    def test_does_not_support_unknown_hip3(self) -> None:
        src = YFinanceSource()
        assert not src.supports("xyz:UNKNOWN_COIN_NOBODY_HAS_LISTED", "1d")
        # Pure crypto majors pass through in this adapter's "bare ticker"
        # mode; that is intentional — fetch will fail at yfinance level if
        # the ticker genuinely doesn't exist, but supports() can't tell that
        # without a network call. Explicit HIP-3 unknowns ARE caught above.

    def test_does_not_support_interval_not_in_yf_list(self) -> None:
        src = YFinanceSource()
        assert not src.supports("xyz:TSLA", "4h")

    def test_fetch_normalizes_canonical_frame(self) -> None:
        captured_kwargs: dict[str, object] = {}

        def fake_download(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return _yf_sample_df()

        src = YFinanceSource(download_fn=fake_download)
        frame = src.fetch_candles(
            "xyz:TSLA",
            "1h",
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 2, tzinfo=UTC),
        )

        assert list(frame.bars.columns) == CANDLE_COLUMNS
        assert len(frame.bars) == 3
        assert frame.source == "yfinance"
        assert frame.symbol == "xyz:TSLA"
        assert frame.bars["close"].tolist() == [101.0, 102.0, 103.0]
        assert captured_kwargs["tickers"] == "TSLA"
        assert captured_kwargs["interval"] == "1h"

    def test_fetch_handles_multiindex_columns(self) -> None:
        # yfinance sometimes returns a MultiIndex for single-ticker downloads.
        df = _yf_sample_df()
        df.columns = pd.MultiIndex.from_tuples([(c, "TSLA") for c in df.columns])

        src = YFinanceSource(download_fn=lambda *a, **kw: df)
        frame = src.fetch_candles(
            "xyz:TSLA",
            "1h",
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 2, tzinfo=UTC),
        )
        assert list(frame.bars.columns) == CANDLE_COLUMNS
        assert len(frame.bars) == 3

    def test_fetch_empty_on_yfinance_exception(self) -> None:
        def bad_download(*a, **kw):
            raise RuntimeError("yahoo dead")

        src = YFinanceSource(download_fn=bad_download)
        frame = src.fetch_candles(
            "xyz:TSLA",
            "1d",
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 10, tzinfo=UTC),
        )
        assert frame.is_empty

    def test_fetch_empty_on_empty_response(self) -> None:
        src = YFinanceSource(download_fn=lambda *a, **kw: pd.DataFrame())
        frame = src.fetch_candles(
            "xyz:TSLA",
            "1d",
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 10, tzinfo=UTC),
        )
        assert frame.is_empty


class TestHip3Map:
    @pytest.mark.parametrize(
        "symbol,expected",
        [
            ("xyz:TSLA", "TSLA"),
            ("xyz:SP500", "SPY"),
            ("cash:GOLD", "GC=F"),
            ("SPY", "SPY"),  # bare passes through
        ],
    )
    def test_yfinance_ticker_for(self, symbol, expected) -> None:
        assert yfinance_ticker_for(symbol) == expected

    def test_unknown_hip3_returns_none(self) -> None:
        assert yfinance_ticker_for("xyz:NONEXISTENT_COIN_12345") is None

    def test_coverage_of_core_hip3_listings(self) -> None:
        """The table must cover every stock + index + commodity in OVERHAUL_PLAN §5."""
        required = [
            "xyz:NVDA", "xyz:TSLA", "xyz:AAPL", "xyz:MSFT", "xyz:AMZN", "xyz:META",
            "xyz:SP500", "xyz:XYZ100",
            "cash:GOLD", "cash:SILVER", "cash:OIL", "cash:CORN", "cash:WHEAT",
        ]
        for sym in required:
            assert sym in HIP3_TO_YFINANCE, f"Missing HIP-3 mapping: {sym}"
