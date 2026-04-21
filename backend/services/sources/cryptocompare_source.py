"""CryptoCompareSource — deep crypto OHLCV history.

Free tier is generous (~250k calls/month with a key, 100k without).
Coverage is excellent for BTC/ETH/SOL/etc. going back to each asset's
launch.

Docs: https://min-api.cryptocompare.com/documentation
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx
import pandas as pd

from backend.services.credentials_store import CredentialsStore
from backend.services.sources.base import CandleFrame, empty_candle_frame

logger = logging.getLogger(__name__)

CC_BASE = "https://min-api.cryptocompare.com/data/v2"

_INTERVAL_MAP = {
    "1m": ("histominute", 1),
    "5m": ("histominute", 5),
    "15m": ("histominute", 15),
    "30m": ("histominute", 30),
    "1h": ("histohour", 1),
    "4h": ("histohour", 4),
    "1d": ("histoday", 1),
}


class CryptoCompareSource:
    name = "cryptocompare"

    def __init__(
        self,
        credentials: CredentialsStore | None = None,
        *,
        api_key: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._credentials = credentials
        self._api_key_override = api_key
        self._client = httpx.Client(timeout=timeout)

    def _key(self) -> str | None:
        if self._api_key_override:
            return self._api_key_override
        if self._credentials is None:
            return None
        cred = self._credentials.first_for("cryptocompare")
        return cred.api_key if cred and cred.api_key else None

    def supports(self, symbol: str, interval: str) -> bool:
        if interval not in _INTERVAL_MAP:
            return False
        # Crypto ticker only — drop Hyperliquid perp prefixes etc.
        return bool(symbol) and ":" not in symbol and not symbol.startswith(("^", "CL=", "GC=", "SI="))

    def earliest_available(self, symbol: str, interval: str) -> datetime | None:  # noqa: ARG002
        return datetime(2010, 1, 1, tzinfo=UTC)

    def fetch_candles(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
    ) -> CandleFrame:
        endpoint, aggregate = _INTERVAL_MAP[interval]
        url = f"{CC_BASE}/{endpoint}"

        # CryptoCompare returns max 2000 bars per call; walk backwards in
        # pages when the requested range is larger.
        all_rows: list[dict[str, Any]] = []
        to_ts = int(end.timestamp())
        min_ts = int(start.timestamp())
        headers: dict[str, str] = {}
        key = self._key()
        if key:
            headers["Authorization"] = f"Apikey {key}"

        for _ in range(20):  # cap pagination at ~40k bars per fetch
            params: dict[str, Any] = {
                "fsym": symbol.upper(),
                "tsym": "USD",
                "limit": 2000,
                "aggregate": aggregate,
                "toTs": to_ts,
            }
            resp = self._client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("Response") != "Success":
                raise RuntimeError(f"CryptoCompare error: {payload.get('Message', payload)}")
            bars = payload.get("Data", {}).get("Data", [])
            if not bars:
                break
            all_rows.extend(bars)
            earliest_in_page = min(b["time"] for b in bars)
            if earliest_in_page <= min_ts:
                break
            to_ts = earliest_in_page - 1

        if not all_rows:
            return _empty_cf(symbol, interval, self.name)

        now = pd.Timestamp.now(tz="UTC")
        rows: list[dict[str, Any]] = []
        for b in all_rows:
            t = int(b.get("time", 0))
            if t < min_ts:
                continue
            rows.append({
                "timestamp": pd.Timestamp(t, unit="s", tz="UTC"),
                "open": float(b.get("open", 0)),
                "high": float(b.get("high", 0)),
                "low": float(b.get("low", 0)),
                "close": float(b.get("close", 0)),
                "volume": float(b.get("volumeto", 0)),
                "trades": pd.NA,
                "source": self.name,
                "ingested_at": now,
            })
        if not rows:
            return _empty_cf(symbol, interval, self.name)
        df = pd.DataFrame(rows).drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
        return CandleFrame(symbol=symbol, interval=interval, source=self.name, bars=df)


def _empty_cf(symbol: str, interval: str, source: str) -> CandleFrame:
    return CandleFrame(symbol=symbol, interval=interval, source=source, bars=empty_candle_frame())
