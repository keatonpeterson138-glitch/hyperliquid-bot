"""Binance spot-klines adapter.

Public endpoint — no auth. Covers crypto history back to ~2017-08-17
for majors. Used to stitch deep pre-Hyperliquid history for BTC/ETH/SOL.
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

import httpx
import pandas as pd

from backend.services.sources.base import (
    CANDLE_COLUMNS,
    CandleFrame,
    empty_candle_frame,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://api.binance.com/api/v3/klines"
_LIMIT_PER_CALL = 1000

_INTERVAL_MS: dict[str, int] = {
    "1m": 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}

# Which base-currency quote to pair against. USDT is the deepest market.
_QUOTE = "USDT"

# Tentative earliest history per base (documented cutoffs — used for planning,
# not strict enforcement). Unknown assets fall back to None.
_EARLIEST: dict[str, datetime] = {
    "BTC": datetime(2017, 8, 17, tzinfo=UTC),
    "ETH": datetime(2017, 8, 17, tzinfo=UTC),
    "SOL": datetime(2020, 8, 11, tzinfo=UTC),
    "LTC": datetime(2017, 12, 13, tzinfo=UTC),
    "BNB": datetime(2017, 11, 6, tzinfo=UTC),
}


class BinanceSource:
    """Historical + recent crypto candles via Binance spot.

    Only crypto. HIP-3 symbols (``xyz:TSLA`` etc.) are rejected in
    ``supports()``.
    """

    name = "binance"

    def __init__(
        self,
        *,
        http_client: httpx.Client | None = None,
        request_timeout_s: float = 10.0,
        retry_attempts: int = 3,
        retry_base_delay_s: float = 1.0,
    ) -> None:
        self._client = http_client or httpx.Client(timeout=request_timeout_s)
        self._owns_client = http_client is None
        self.retry_attempts = max(1, retry_attempts)
        self.retry_base_delay_s = retry_base_delay_s

    def __enter__(self) -> BinanceSource:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def supports(self, symbol: str, interval: str) -> bool:
        if ":" in symbol:
            return False
        return interval in _INTERVAL_MS and bool(symbol)

    def earliest_available(self, symbol: str, interval: str) -> datetime | None:
        return _EARLIEST.get(symbol.upper())

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

        pair = _to_binance_pair(symbol)
        start_ms = _utc_ms(start)
        end_ms = _utc_ms(end)
        step_ms = _INTERVAL_MS[interval] * _LIMIT_PER_CALL

        rows: list[list[object]] = []
        cursor = start_ms
        while cursor < end_ms:
            chunk_end = min(cursor + step_ms - 1, end_ms)
            chunk = self._fetch_chunk(pair, interval, cursor, chunk_end)
            if not chunk:
                break
            rows.extend(chunk)
            last_open = int(chunk[-1][0])
            next_cursor = last_open + _INTERVAL_MS[interval]
            if next_cursor <= cursor:
                break
            cursor = next_cursor

        if not rows:
            return CandleFrame(symbol, interval, self.name, empty_candle_frame())

        bars = _normalize_binance_klines(rows)
        bars["source"] = self.name
        bars["ingested_at"] = pd.Timestamp.now(tz="UTC")
        bars = bars[CANDLE_COLUMNS]
        bars = bars.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
        return CandleFrame(symbol, interval, self.name, bars)

    def _fetch_chunk(
        self, pair: str, interval: str, start_ms: int, end_ms: int
    ) -> list[list[object]]:
        params = {
            "symbol": pair,
            "interval": interval,
            "startTime": start_ms,
            "endTime": end_ms,
            "limit": _LIMIT_PER_CALL,
        }
        last_exc: Exception | None = None
        for attempt in range(self.retry_attempts):
            try:
                resp = self._client.get(BASE_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, list):
                    logger.warning("Binance klines non-list response: %s", data)
                    return []
                return data
            except (httpx.HTTPError, ValueError) as exc:
                last_exc = exc
                if attempt == self.retry_attempts - 1:
                    break
                time.sleep(self.retry_base_delay_s * (2**attempt))
        logger.error("Binance fetch failed for %s: %s", pair, last_exc)
        return []


def _to_binance_pair(symbol: str) -> str:
    return f"{symbol.upper()}{_QUOTE}"


def _utc_ms(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.astimezone(UTC).timestamp() * 1000)


def _normalize_binance_klines(rows: list[list[object]]) -> pd.DataFrame:
    """Binance kline row layout:

    ``[open_time, open, high, low, close, volume, close_time, quote_volume,
        number_of_trades, taker_buy_base_volume, taker_buy_quote_volume, ignore]``
    """
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime([int(r[0]) for r in rows], unit="ms", utc=True),
            "open": [float(r[1]) for r in rows],
            "high": [float(r[2]) for r in rows],
            "low": [float(r[3]) for r in rows],
            "close": [float(r[4]) for r in rows],
            "volume": [float(r[5]) for r in rows],
            "trades": pd.array([int(r[8]) for r in rows], dtype="Int64"),
        }
    )
