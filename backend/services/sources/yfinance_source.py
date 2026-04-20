"""yfinance adapter for equities + commodities + index proxies.

Maps HIP-3 symbols (``xyz:TSLA``, ``cash:GOLD``, etc.) to their underlying
Yahoo Finance tickers via ``hip3_map.yfinance_ticker_for``. Reaches back
decades for stocks and commodity futures.

yfinance is a soft dependency — imported lazily so the rest of the
service layer works without it installed (and tests can mock it).
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd

from backend.services.sources.base import (
    CANDLE_COLUMNS,
    CandleFrame,
    empty_candle_frame,
)
from backend.services.sources.hip3_map import yfinance_ticker_for

logger = logging.getLogger(__name__)

# yfinance supports these intervals; 4h is aggregated from 1h in a later pass.
_INTERVAL_TO_YF: dict[str, str] = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "1h": "1h",
    "1d": "1d",
    "1w": "1wk",
}

# yfinance imposes intraday-history limits per interval.
_MAX_LOOKBACK_DAYS: dict[str, int] = {
    "1m": 7,      # 7-day cap on 1m
    "5m": 60,
    "15m": 60,
    "1h": 730,    # 2 years
    "1d": 20_000, # effectively full history
    "1w": 20_000,
}


class YFinanceSource:
    """Equities, commodities, and index proxies via yfinance.

    Accept injected ``download_fn`` for tests — defaults to
    ``yfinance.download`` resolved lazily on first call.
    """

    name = "yfinance"

    def __init__(self, *, download_fn: Any = None) -> None:
        self._download_fn = download_fn

    def _download(self, *args: Any, **kwargs: Any) -> pd.DataFrame:
        if self._download_fn is not None:
            return self._download_fn(*args, **kwargs)
        # Lazy import — keeps yfinance optional.
        import yfinance  # type: ignore[import-not-found]

        return yfinance.download(*args, **kwargs)

    def supports(self, symbol: str, interval: str) -> bool:
        if interval not in _INTERVAL_TO_YF:
            return False
        return yfinance_ticker_for(symbol) is not None

    def earliest_available(self, symbol: str, interval: str) -> datetime | None:
        # yfinance doesn't expose a cheap lookup; daily typically covers
        # decades for equities. Returning None signals "unknown — try it".
        return None

    def fetch_candles(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
    ) -> CandleFrame:
        if not self.supports(symbol, interval):
            raise ValueError(f"Unsupported symbol/interval: {symbol}/{interval}")
        if start >= end:
            return CandleFrame(symbol, interval, self.name, empty_candle_frame())

        ticker = yfinance_ticker_for(symbol)
        assert ticker is not None  # checked by supports()

        # Intraday lookback caps — clamp the start if it exceeds yfinance's window.
        cap_days = _MAX_LOOKBACK_DAYS[interval]
        earliest_permitted = datetime.now(UTC) - timedelta(days=cap_days)
        effective_start = max(start, earliest_permitted)

        try:
            df = self._download(
                tickers=ticker,
                start=effective_start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                interval=_INTERVAL_TO_YF[interval],
                auto_adjust=False,
                progress=False,
                threads=False,
            )
        except Exception as exc:
            logger.error("yfinance download failed for %s: %s", ticker, exc)
            return CandleFrame(symbol, interval, self.name, empty_candle_frame())

        if df is None or df.empty:
            return CandleFrame(symbol, interval, self.name, empty_candle_frame())

        bars = _normalize_yfinance_frame(df)
        bars["source"] = self.name
        bars["ingested_at"] = pd.Timestamp.now(tz="UTC")
        bars = bars[CANDLE_COLUMNS]
        bars = bars.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
        return CandleFrame(symbol, interval, self.name, bars)


def _normalize_yfinance_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Convert a yfinance OHLCV DataFrame to our canonical columns.

    yfinance returns columns ``[Open, High, Low, Close, Adj Close, Volume]``
    indexed by ``Datetime`` (tz-aware) or ``Date`` (naive). Sometimes it
    returns a MultiIndex columns frame when a single ticker is downloaded —
    we flatten defensively.
    """
    # Flatten multi-level columns if yfinance returned them.
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]

    # Rename / select canonical columns.
    colmap = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}
    bars = df.rename(columns=colmap)[list(colmap.values())].copy()

    # Timestamp column from index.
    idx = pd.to_datetime(df.index, utc=True)
    bars.insert(0, "timestamp", idx)
    bars = bars.reset_index(drop=True)

    # Fill the canonical optional columns.
    bars["trades"] = pd.array([pd.NA] * len(bars), dtype="Int64")
    return bars
