"""Live network integration tests — run explicitly with::

    pytest tests/live/ -m live -v

These hit real public APIs (Hyperliquid / Coinbase / yfinance / CoinGecko /
CryptoCompare / FRED / Alpha Vantage) and confirm each adapter returns
real data via the canonical ``CandleFrame`` shape. Skipped by default
because they're slow + flaky + rate-limited; run manually when
diagnosing "why does the loader not work?".

Binance is always expected to fail or return empty when run from a US
IP (HTTP 451) — we assert it either works or errors, not both.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.live


@pytest.fixture
def recent_range():
    end = datetime.now(UTC)
    return end - timedelta(days=3), end


@pytest.fixture
def weekly_range():
    end = datetime.now(UTC)
    return end - timedelta(days=7), end


def _assert_candle_frame_has_rows(cf, min_rows: int = 1) -> None:
    assert cf is not None, "source returned None"
    assert hasattr(cf, "bars"), "return isn't a CandleFrame"
    n = len(cf.bars)
    assert n >= min_rows, f"expected >={min_rows} rows, got {n}"
    cols = set(cf.bars.columns)
    for required in ("timestamp", "open", "high", "low", "close", "volume", "source"):
        assert required in cols, f"missing column {required}: have {sorted(cols)}"


def test_hyperliquid_btc_1h(recent_range):
    from backend.services.sources.hyperliquid_source import HyperliquidSource
    start, end = recent_range
    cf = HyperliquidSource().fetch_candles("BTC", "1h", start, end)
    _assert_candle_frame_has_rows(cf, min_rows=24)


def test_coinbase_btc_1h(recent_range):
    from backend.services.sources.coinbase_source import CoinbaseSource
    start, end = recent_range
    cf = CoinbaseSource().fetch_candles("BTC", "1h", start, end)
    _assert_candle_frame_has_rows(cf, min_rows=24)


def test_yfinance_aapl_1d(weekly_range):
    from backend.services.sources.yfinance_source import YFinanceSource
    start, end = weekly_range
    cf = YFinanceSource().fetch_candles("AAPL", "1d", start, end)
    # Weekends -> fewer bars; just require at least 1 trading day.
    _assert_candle_frame_has_rows(cf, min_rows=1)


def test_coingecko_btc_1h(recent_range):
    from backend.services.sources.coingecko_source import CoinGeckoSource
    start, end = recent_range
    cf = CoinGeckoSource().fetch_candles("BTC", "1h", start, end)
    _assert_candle_frame_has_rows(cf, min_rows=24)


def test_cryptocompare_btc_1h(recent_range):
    from backend.services.sources.cryptocompare_source import CryptoCompareSource
    start, end = recent_range
    cf = CryptoCompareSource().fetch_candles("BTC", "1h", start, end)
    _assert_candle_frame_has_rows(cf, min_rows=24)


def test_alphavantage_aapl_1d_with_env_key(weekly_range):
    key = os.environ.get("ALPHA_VANTAGE_KEY")
    if not key:
        pytest.skip("set ALPHA_VANTAGE_KEY env var to run this test")
    from backend.services.sources.alphavantage_source import AlphaVantageSource
    start, end = weekly_range
    cf = AlphaVantageSource(api_key=key).fetch_candles("AAPL", "1d", start, end)
    _assert_candle_frame_has_rows(cf, min_rows=1)


def test_fred_dgs10_1d_with_env_key():
    key = os.environ.get("FRED_API_KEY")
    if not key:
        pytest.skip("set FRED_API_KEY env var to run this test")
    from backend.services.sources.fred_source import FREDSource
    end = datetime.now(UTC)
    start = end - timedelta(days=365)
    cf = FREDSource(api_key=key).fetch_candles("DGS10", "1d", start, end)
    _assert_candle_frame_has_rows(cf, min_rows=100)
