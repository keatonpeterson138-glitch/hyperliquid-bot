"""Hyperliquid candle adapter.

Hits the public Info API's ``candleSnapshot`` endpoint. Supports native
perps and HIP-3 builder perps (via ``dex:symbol`` format, e.g. ``xyz:TSLA``).
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta

import httpx
import pandas as pd

from backend.services.sources.base import (
    CANDLE_COLUMNS,
    CandleFrame,
    empty_candle_frame,
)

logger = logging.getLogger(__name__)

MAINNET_URL = "https://api.hyperliquid.xyz/info"
TESTNET_URL = "https://api.hyperliquid-testnet.xyz/info"

# Hyperliquid's candleSnapshot caps returns at ~5000 bars. We paginate
# conservatively below that.
_MAX_BARS_PER_CALL = 4000

_INTERVAL_MS: dict[str, int] = {
    "1m": 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}


class HyperliquidSource:
    """Primary source for native + HIP-3 perps.

    ``dex`` is inferred from ``symbol`` — a ``dex:coin`` symbol routes to
    that dex's namespace; otherwise native perps.
    """

    name = "hyperliquid"

    def __init__(
        self,
        *,
        testnet: bool = False,
        http_client: httpx.Client | None = None,
        request_timeout_s: float = 10.0,
        retry_attempts: int = 3,
        retry_base_delay_s: float = 1.0,
    ) -> None:
        self.testnet = testnet
        self.base_url = TESTNET_URL if testnet else MAINNET_URL
        self._client = http_client or httpx.Client(timeout=request_timeout_s)
        self._owns_client = http_client is None
        self.retry_attempts = max(1, retry_attempts)
        self.retry_base_delay_s = retry_base_delay_s

    def __enter__(self) -> HyperliquidSource:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    # ── DataSource protocol ────────────────────────────────────────────────

    def supports(self, symbol: str, interval: str) -> bool:
        return interval in _INTERVAL_MS and bool(symbol)

    def earliest_available(self, symbol: str, interval: str) -> datetime | None:
        # Hyperliquid's retention varies per asset; we don't have a cheap probe.
        # Caller can fall back on the earliest timestamp of a small historical
        # probe if they need it. Returning None means "unknown".
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

        start_ms = _to_utc_ms(start)
        end_ms = _to_utc_ms(end)
        step_ms = _INTERVAL_MS[interval] * _MAX_BARS_PER_CALL

        dex = _dex_from_symbol(symbol)
        coin = _coin_from_symbol(symbol)

        collected: list[dict[str, object]] = []
        cursor_ms = start_ms
        while cursor_ms < end_ms:
            chunk_end_ms = min(cursor_ms + step_ms, end_ms)
            raw = self._fetch_chunk(coin, interval, cursor_ms, chunk_end_ms, dex)
            if not raw:
                break
            collected.extend(raw)
            # Advance cursor past the last returned candle.
            last_ts = int(raw[-1]["t"])
            next_cursor = last_ts + _INTERVAL_MS[interval]
            if next_cursor <= cursor_ms:
                break  # defensive — avoid infinite loop
            cursor_ms = next_cursor

        if not collected:
            return CandleFrame(symbol, interval, self.name, empty_candle_frame())

        bars = _normalize_raw_candles(collected)
        bars["source"] = self.name
        bars["ingested_at"] = pd.Timestamp.now(tz="UTC")
        bars = bars[CANDLE_COLUMNS]
        bars = bars.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
        return CandleFrame(symbol, interval, self.name, bars)

    # ── Internal ───────────────────────────────────────────────────────────

    def _fetch_chunk(
        self,
        coin: str,
        interval: str,
        start_ms: int,
        end_ms: int,
        dex: str,
    ) -> list[dict[str, object]]:
        payload = {
            "type": "candleSnapshot",
            "req": {
                "coin": coin,
                "interval": interval,
                "startTime": start_ms,
                "endTime": end_ms,
            },
        }
        if dex:
            payload["req"]["dex"] = dex

        last_exc: Exception | None = None
        for attempt in range(self.retry_attempts):
            try:
                resp = self._client.post(self.base_url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, list):
                    logger.warning("Hyperliquid candleSnapshot non-list response: %s", data)
                    return []
                return data
            except (httpx.HTTPError, ValueError) as exc:
                last_exc = exc
                if attempt == self.retry_attempts - 1:
                    break
                delay = self.retry_base_delay_s * (2**attempt)
                logger.warning(
                    "Hyperliquid fetch retry %d/%d for %s after %s (sleep %.1fs)",
                    attempt + 1,
                    self.retry_attempts,
                    coin,
                    exc,
                    delay,
                )
                time.sleep(delay)
        logger.error("Hyperliquid fetch failed for %s: %s", coin, last_exc)
        return []


# ── Helpers ────────────────────────────────────────────────────────────────


def _dex_from_symbol(symbol: str) -> str:
    if ":" in symbol:
        return symbol.split(":", 1)[0]
    return ""


def _coin_from_symbol(symbol: str) -> str:
    if ":" in symbol:
        return symbol.split(":", 1)[1]
    return symbol


def _to_utc_ms(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.astimezone(UTC).timestamp() * 1000)


def _normalize_raw_candles(raw: list[dict[str, object]]) -> pd.DataFrame:
    """Convert Hyperliquid's candle objects to our canonical DataFrame."""
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime([int(c["t"]) for c in raw], unit="ms", utc=True),
            "open": [float(c["o"]) for c in raw],
            "high": [float(c["h"]) for c in raw],
            "low": [float(c["l"]) for c in raw],
            "close": [float(c["c"]) for c in raw],
            "volume": [float(c["v"]) for c in raw],
            "trades": pd.array(
                [int(c.get("n", 0)) if c.get("n") is not None else pd.NA for c in raw],
                dtype="Int64",
            ),
        }
    )


# Small re-export — occasionally useful in tests that construct a wall-clock range.
def default_recent_range(bars: int, interval: str) -> tuple[datetime, datetime]:
    end = datetime.now(UTC)
    start = end - timedelta(milliseconds=_INTERVAL_MS[interval] * bars)
    return start, end
