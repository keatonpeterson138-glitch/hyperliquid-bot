"""FREDSource — Federal Reserve Economic Data.

FRED exposes thousands of macro/rates/inflation/labor series at
https://api.stlouisfed.org/fred/. Requires a free API key (register
at https://fred.stlouisfed.org/docs/api/api_key.html), which we pull
from the CredentialsStore under provider='fred' or the legacy
'alpha_vantage'-style slot.

This source is unusual vs the other OHLCV adapters: FRED series are
value-per-date, not OHLCV. We shim them into the OHLCV schema with
O=H=L=C=value and volume=0 so they flow through the same catalog +
chart pipeline. Intervals are limited to daily and above — FRED data
is never sub-daily.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx
import pandas as pd

from backend.services.credentials_store import CredentialsStore
from backend.services.sources.base import CandleFrame, empty_candle_frame

logger = logging.getLogger(__name__)

FRED_BASE = "https://api.stlouisfed.org/fred"

# Handful of the highest-signal series for trading.
POPULAR_SERIES: list[dict[str, Any]] = [
    {"id": "DFF",      "name": "Federal Funds Effective Rate",                "category": "rates"},
    {"id": "DGS10",    "name": "10-Year Treasury Constant Maturity",          "category": "rates"},
    {"id": "DGS2",     "name": "2-Year Treasury Constant Maturity",           "category": "rates"},
    {"id": "T10Y2Y",   "name": "10Y-2Y Treasury Yield Spread",                "category": "rates"},
    {"id": "DFII10",   "name": "10-Year TIPS (real rate)",                    "category": "rates"},
    {"id": "T10YIE",   "name": "10-Year Breakeven Inflation",                 "category": "inflation"},
    {"id": "T5YIFR",   "name": "5-Year Forward Inflation Expectation",        "category": "inflation"},
    {"id": "CPIAUCSL", "name": "Consumer Price Index (All Urban)",            "category": "inflation"},
    {"id": "CPILFESL", "name": "Core CPI (ex food + energy)",                 "category": "inflation"},
    {"id": "UNRATE",   "name": "Unemployment Rate",                           "category": "labor"},
    {"id": "PAYEMS",   "name": "Nonfarm Payrolls",                            "category": "labor"},
    {"id": "ICSA",     "name": "Initial Jobless Claims",                      "category": "labor"},
    {"id": "GDPC1",    "name": "Real GDP",                                    "category": "growth"},
    {"id": "INDPRO",   "name": "Industrial Production",                       "category": "growth"},
    {"id": "UMCSENT",  "name": "U. Michigan Consumer Sentiment",              "category": "sentiment"},
    {"id": "VIXCLS",   "name": "VIX Close",                                   "category": "risk"},
    {"id": "DTWEXBGS", "name": "Broad Dollar Index (Goods + Services)",       "category": "dollar"},
    {"id": "WALCL",    "name": "Fed Total Assets (Balance Sheet)",            "category": "liquidity"},
    {"id": "M2SL",     "name": "M2 Money Stock",                              "category": "liquidity"},
    {"id": "RRPONTSYD","name": "Reverse Repo Outstanding",                    "category": "liquidity"},
]


class FREDSource:
    """DataSource adapter. Only serves daily+; anything sub-daily falls
    back to the router's next source."""

    name = "fred"

    def __init__(self, credentials: CredentialsStore | None = None, *, api_key: str | None = None, timeout: float = 10.0) -> None:
        self._credentials = credentials
        self._api_key_override = api_key
        self._client = httpx.Client(timeout=timeout)

    def _key(self) -> str | None:
        if self._api_key_override:
            return self._api_key_override
        if self._credentials is None:
            return None
        cred = self._credentials.first_for("fred")
        if cred and cred.api_key:
            return cred.api_key
        return None

    def supports(self, symbol: str, interval: str) -> bool:
        # FRED series are daily or lower-frequency. Accept "1d" and upward.
        if interval not in {"1d", "3d", "1w", "1M"}:
            return False
        # A "FRED symbol" is the series_id (DGS10, DFF, etc.). We treat any
        # uppercase alnum-with-underscores as potentially FRED.
        return bool(symbol) and not symbol.startswith(("^", "CL=", "GC=", "SI="))

    def earliest_available(self, symbol: str, interval: str) -> datetime | None:  # noqa: ARG002
        # FRED history goes back to the 1950s+ for many series; we claim 1980
        # as a conservative floor so the router asks us for the full range.
        return datetime(1980, 1, 1)

    def fetch_candles(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
    ) -> CandleFrame:
        key = self._key()
        if not key:
            raise RuntimeError("FRED requires an API key — add one in Sidebar → API Keys under provider 'fred'.")

        url = f"{FRED_BASE}/series/observations"
        params = {
            "series_id": symbol,
            "api_key": key,
            "file_type": "json",
            "observation_start": start.strftime("%Y-%m-%d"),
            "observation_end": end.strftime("%Y-%m-%d"),
        }
        resp = self._client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        obs = data.get("observations", []) if isinstance(data, dict) else []

        rows: list[dict[str, Any]] = []
        for o in obs:
            try:
                v = float(o["value"]) if o.get("value") not in (".", None, "") else None
            except (TypeError, ValueError):
                v = None
            if v is None:
                continue
            try:
                ts = pd.Timestamp(o["date"]).tz_localize("UTC")
            except Exception:  # noqa: BLE001
                continue
            rows.append({
                "timestamp": ts,
                "open": v, "high": v, "low": v, "close": v,
                "volume": 0.0,
                "trades": pd.NA,
                "source": self.name,
                "ingested_at": pd.Timestamp.now(tz="UTC"),
            })
        if not rows:
            return CandleFrame(symbol=symbol, interval=interval, source=self.name, bars=empty_candle_frame())
        df = pd.DataFrame(rows)
        return CandleFrame(symbol=symbol, interval=interval, source=self.name, bars=df)

    def search_series(self, query: str, limit: int = 30) -> list[dict[str, Any]]:
        """Wrap FRED's /series/search so the UI can browse the full catalog."""
        key = self._key()
        if not key:
            return []
        url = f"{FRED_BASE}/series/search"
        params = {
            "search_text": query,
            "api_key": key,
            "file_type": "json",
            "limit": limit,
        }
        try:
            resp = self._client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("FRED search failed: %s", exc)
            return []
        items = data.get("seriess", []) if isinstance(data, dict) else []
        return [
            {
                "id": s.get("id"),
                "name": s.get("title"),
                "units": s.get("units"),
                "frequency": s.get("frequency"),
                "category": s.get("group_popularity") or "other",
                "observation_start": s.get("observation_start"),
                "observation_end": s.get("observation_end"),
                "last_updated": s.get("last_updated"),
            }
            for s in items
        ]
