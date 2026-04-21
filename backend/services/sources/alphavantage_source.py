"""AlphaVantageSource — daily + intraday stocks via Alpha Vantage.

Free tier is 25 requests/day + 5/minute, which is too slow for deep
backfills but fine for filling gaps yfinance leaves. API key pulled
from the CredentialsStore under provider='alpha_vantage'.

Docs: https://www.alphavantage.co/documentation/
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

AV_BASE = "https://www.alphavantage.co/query"

_INTRADAY_INTERVAL_MAP = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "60min",
}


class AlphaVantageSource:
    name = "alphavantage"

    def __init__(
        self,
        credentials: CredentialsStore | None = None,
        *,
        api_key: str | None = None,
        timeout: float = 20.0,
        outputsize: str = "compact",  # free tier only supports compact (100 bars)
    ) -> None:
        self._credentials = credentials
        self._api_key_override = api_key
        self._client = httpx.Client(timeout=timeout)
        self._outputsize = outputsize

    def _key(self) -> str | None:
        if self._api_key_override:
            return self._api_key_override
        if self._credentials is None:
            return None
        cred = self._credentials.first_for("alpha_vantage")
        return cred.api_key if cred and cred.api_key else None

    def supports(self, symbol: str, interval: str) -> bool:
        if interval not in {"1m", "5m", "15m", "30m", "1h", "1d"}:
            return False
        # Stocks only — skip crypto and Hyperliquid-style perp names.
        if symbol.startswith(("^", "CL=", "GC=", "SI=", "DX-")):
            return False
        if ":" in symbol:
            return False
        return True

    def earliest_available(self, symbol: str, interval: str) -> datetime | None:  # noqa: ARG002
        if interval == "1d":
            return datetime(1999, 1, 1, tzinfo=UTC)
        # Intraday only goes back ~2 years on Alpha Vantage premium, less on free.
        return datetime(2022, 1, 1, tzinfo=UTC)

    def fetch_candles(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
    ) -> CandleFrame:
        key = self._key()
        if not key:
            raise RuntimeError(
                "Alpha Vantage needs an API key — Sidebar → API Keys → provider 'alpha_vantage'."
            )

        if interval == "1d":
            params = {
                "function": "TIME_SERIES_DAILY",
                "symbol": symbol,
                "outputsize": self._outputsize,
                "datatype": "json",
                "apikey": key,
            }
            time_key = "Time Series (Daily)"
        else:
            iv = _INTRADAY_INTERVAL_MAP.get(interval)
            if iv is None:
                return _empty_cf(symbol, interval, self.name)
            params = {
                "function": "TIME_SERIES_INTRADAY",
                "symbol": symbol,
                "interval": iv,
                "outputsize": self._outputsize,
                "datatype": "json",
                "apikey": key,
            }
            time_key = f"Time Series ({iv})"

        resp = self._client.get(AV_BASE, params=params)
        resp.raise_for_status()
        data = resp.json()
        series = data.get(time_key) if isinstance(data, dict) else None

        # Rate-limit and error conditions come back in "Information" or "Note".
        if not isinstance(series, dict):
            note = data.get("Note") or data.get("Information") or data.get("Error Message") or "unknown"
            raise RuntimeError(f"Alpha Vantage response empty: {note}")

        start_ts = _to_utc(start)
        end_ts = _to_utc(end)
        now = pd.Timestamp.now(tz="UTC")
        rows: list[dict[str, Any]] = []
        for ts_str, payload in series.items():
            try:
                ts = pd.Timestamp(ts_str).tz_localize("UTC")
            except Exception:  # noqa: BLE001
                continue
            if ts < start_ts or ts > end_ts:
                continue
            try:
                rows.append({
                    "timestamp": ts,
                    "open": float(payload["1. open"]),
                    "high": float(payload["2. high"]),
                    "low": float(payload["3. low"]),
                    "close": float(payload["4. close"]),
                    "volume": float(payload.get("5. volume", 0.0) or 0.0),
                    "trades": pd.NA,
                    "source": self.name,
                    "ingested_at": now,
                })
            except (KeyError, TypeError, ValueError):
                continue

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
