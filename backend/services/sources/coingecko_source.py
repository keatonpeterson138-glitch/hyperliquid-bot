"""CoinGeckoSource — free public crypto data.

No API key required for the free tier. Rate limit is ~10-30 calls/min.
Coverage: basically every tradeable crypto, ~1 year of historical on
the free /market_chart endpoint (longer windows are paid).

Docs: https://docs.coingecko.com/reference/introduction
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pandas as pd

from backend.services.sources.base import CandleFrame, empty_candle_frame

logger = logging.getLogger(__name__)

CG_BASE = "https://api.coingecko.com/api/v3"

# Quick lookup: Hyperliquid perp symbol -> CoinGecko coin id.
COIN_ID_MAP: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "HYPE": "hyperliquid",
    "AVAX": "avalanche-2",
    "ARB": "arbitrum",
    "DOGE": "dogecoin",
    "LINK": "chainlink",
    "XRP": "ripple",
    "LTC": "litecoin",
    "ADA": "cardano",
    "DOT": "polkadot",
    "BNB": "binancecoin",
    "MATIC": "matic-network",
    "ATOM": "cosmos",
    "UNI": "uniswap",
    "AAVE": "aave",
    "OP": "optimism",
    "NEAR": "near",
    "APT": "aptos",
}


class CoinGeckoSource:
    name = "coingecko"

    def __init__(self, *, api_key: str | None = None, timeout: float = 10.0) -> None:
        self._api_key = api_key  # pro-tier; free tier works keyless
        self._client = httpx.Client(timeout=timeout)

    def supports(self, symbol: str, interval: str) -> bool:
        if interval not in {"1h", "4h", "1d"}:
            return False
        return symbol in COIN_ID_MAP

    def earliest_available(self, symbol: str, interval: str) -> datetime | None:  # noqa: ARG002
        return datetime(2013, 1, 1, tzinfo=UTC)

    def fetch_candles(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
    ) -> CandleFrame:
        coin = COIN_ID_MAP.get(symbol)
        if coin is None:
            return _empty_cf(symbol, interval, self.name)

        # CoinGecko /market_chart returns 1min / 1hr / 1day buckets depending
        # on the 'days' parameter. Use 'max' for deep history (daily only).
        days = max(1, int((end - start).total_seconds() / 86400))
        url = f"{CG_BASE}/coins/{coin}/market_chart"
        params: dict[str, Any] = {"vs_currency": "usd", "days": str(days)}

        headers: dict[str, str] = {}
        if self._api_key:
            headers["x-cg-pro-api-key"] = self._api_key

        resp = self._client.get(url, params=params, headers=headers)
        if resp.status_code == 429:
            raise RuntimeError("CoinGecko rate-limited; back off for ~1 min")
        resp.raise_for_status()
        data = resp.json()

        # prices: [[ts_ms, price], ...] — only close. We synthesise an OHLCV
        # row where O=H=L=C=price, vol=0.
        prices = data.get("prices") or []
        volumes = {int(ts): float(v) for ts, v in (data.get("total_volumes") or [])}

        start_ts = _to_utc(start)
        end_ts = _to_utc(end)
        now = pd.Timestamp.now(tz="UTC")

        rows: list[dict[str, Any]] = []
        for ts_ms, price in prices:
            ts = pd.Timestamp(ts_ms, unit="ms", tz="UTC")
            if ts < start_ts or ts > end_ts:
                continue
            rows.append({
                "timestamp": ts,
                "open": float(price), "high": float(price),
                "low": float(price), "close": float(price),
                "volume": volumes.get(int(ts_ms), 0.0),
                "trades": pd.NA,
                "source": self.name,
                "ingested_at": now,
            })
        if not rows:
            return _empty_cf(symbol, interval, self.name)
        df = pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)
        return CandleFrame(symbol=symbol, interval=interval, source=self.name, bars=df)


def _to_utc(dt: datetime) -> pd.Timestamp:
    ts = pd.Timestamp(dt)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _empty_cf(symbol: str, interval: str, source: str) -> CandleFrame:
    return CandleFrame(symbol=symbol, interval=interval, source=source, bars=empty_candle_frame())
