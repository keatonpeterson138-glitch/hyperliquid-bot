"""Coinbase Exchange candles adapter.

Public historical-candles endpoint — no auth. Reaches back to 2015 for
BTC-USD, making it the deepest-history source for crypto majors.

Coinbase caps each response at 300 candles and requires integer
``granularity`` in seconds; 4h (14400) is **not** supported natively.
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

BASE_URL = "https://api.exchange.coinbase.com/products"
_LIMIT_PER_CALL = 300

_INTERVAL_S: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3_600,
    "1d": 86_400,
    # "6h" is supported by Coinbase (21_600) but we don't currently expose it.
}

_QUOTE = "USD"

_EARLIEST: dict[str, datetime] = {
    "BTC": datetime(2015, 7, 20, tzinfo=UTC),
    "ETH": datetime(2016, 5, 18, tzinfo=UTC),
    "LTC": datetime(2016, 8, 25, tzinfo=UTC),
    "SOL": datetime(2021, 6, 23, tzinfo=UTC),
}


class CoinbaseSource:
    """Historical crypto via Coinbase Exchange public endpoint."""

    name = "coinbase"

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

    def __enter__(self) -> CoinbaseSource:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def supports(self, symbol: str, interval: str) -> bool:
        if not symbol or interval not in _INTERVAL_S:
            return False
        if ":" in symbol or "=" in symbol or symbol.startswith("^"):
            return False
        from backend.services.sources.hyperliquid_source import _NON_HYPERLIQUID_SYMBOLS
        if symbol.upper() in _NON_HYPERLIQUID_SYMBOLS:
            return False
        return True

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

        product = _to_coinbase_product(symbol)
        granularity_s = _INTERVAL_S[interval]
        step_s = granularity_s * _LIMIT_PER_CALL

        rows: list[list[object]] = []
        cursor_s = int(start.astimezone(UTC).timestamp())
        end_s = int(end.astimezone(UTC).timestamp())
        while cursor_s < end_s:
            chunk_end_s = min(cursor_s + step_s, end_s)
            chunk = self._fetch_chunk(product, granularity_s, cursor_s, chunk_end_s)
            if not chunk:
                break
            rows.extend(chunk)
            # Coinbase returns newest-first. Advance cursor past oldest returned.
            oldest_s = int(chunk[-1][0])
            next_cursor = oldest_s + granularity_s if oldest_s >= cursor_s else cursor_s + granularity_s
            # Or just advance by the full window; caller is idempotent via dedupe.
            advanced = max(next_cursor, cursor_s + granularity_s)
            if advanced <= cursor_s:
                break
            cursor_s = min(advanced, chunk_end_s + granularity_s)
            if cursor_s == chunk_end_s + granularity_s and len(chunk) < _LIMIT_PER_CALL:
                # Short page → advance past the entire requested window.
                cursor_s = chunk_end_s

        if not rows:
            return CandleFrame(symbol, interval, self.name, empty_candle_frame())

        bars = _normalize_coinbase_candles(rows)
        bars["source"] = self.name
        bars["ingested_at"] = pd.Timestamp.now(tz="UTC")
        bars = bars[CANDLE_COLUMNS]
        bars = bars.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
        return CandleFrame(symbol, interval, self.name, bars)

    def _fetch_chunk(
        self, product: str, granularity_s: int, start_s: int, end_s: int
    ) -> list[list[object]]:
        url = f"{BASE_URL}/{product}/candles"
        params = {
            "granularity": granularity_s,
            "start": datetime.fromtimestamp(start_s, tz=UTC).isoformat(),
            "end": datetime.fromtimestamp(end_s, tz=UTC).isoformat(),
        }
        last_exc: Exception | None = None
        for attempt in range(self.retry_attempts):
            try:
                resp = self._client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, list):
                    logger.warning("Coinbase candles non-list response: %s", data)
                    return []
                return data
            except (httpx.HTTPError, ValueError) as exc:
                last_exc = exc
                if attempt == self.retry_attempts - 1:
                    break
                time.sleep(self.retry_base_delay_s * (2**attempt))
        logger.error("Coinbase fetch failed for %s: %s", product, last_exc)
        return []


def _to_coinbase_product(symbol: str) -> str:
    return f"{symbol.upper()}-{_QUOTE}"


def _normalize_coinbase_candles(rows: list[list[object]]) -> pd.DataFrame:
    """Coinbase candle row layout:

    ``[time_seconds, low, high, open, close, volume]``  (note: low/high order)
    """
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime([int(r[0]) for r in rows], unit="s", utc=True),
            "open": [float(r[3]) for r in rows],
            "high": [float(r[2]) for r in rows],
            "low": [float(r[1]) for r in rows],
            "close": [float(r[4]) for r in rows],
            "volume": [float(r[5]) for r in rows],
            "trades": pd.array([pd.NA] * len(rows), dtype="Int64"),
        }
    )
