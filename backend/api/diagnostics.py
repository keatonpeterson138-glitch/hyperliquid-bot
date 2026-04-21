"""/diagnostics — real-world health check for every data source.

GET /diagnostics/sources pings each wired source with a canary fetch
(BTC 1h last 3 days; AAPL 1d last week for stock sources; DGS10 1d
last week for FRED). Returns per-source status + latency + sample
rows. The UI Data Sources page calls this on load.

This is what you want when "the loader doesn't work" — it tells you
*which* source is failing and why.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from backend.services.credentials_store import CredentialsStore

logger = logging.getLogger(__name__)

router = APIRouter(tags=["diagnostics"])


def get_credentials_for_diag() -> CredentialsStore | None:
    # Ok to be None — the credential-using sources report "key missing"
    # as a legitimate diagnostic result rather than a 503 on this route.
    return None


CredsDep = Annotated[CredentialsStore | None, Depends(get_credentials_for_diag)]


@dataclass
class SourceDiagnostic:
    name: str
    label: str
    canary: str                       # human-readable description of the probe
    status: str = "unknown"           # 'ok' | 'error' | 'skipped' | 'no_key'
    rows_fetched: int = 0
    latency_ms: int = 0
    earliest: str | None = None
    latest: str | None = None
    sample: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "canary": self.canary,
            "status": self.status,
            "rows_fetched": self.rows_fetched,
            "latency_ms": self.latency_ms,
            "earliest": self.earliest,
            "latest": self.latest,
            "sample": self.sample,
            "error": self.error,
        }


def _probe_candles(source, symbol: str, interval: str, start: datetime, end: datetime, d: SourceDiagnostic) -> None:
    t0 = time.time()
    try:
        if not source.supports(symbol, interval):
            d.status = "skipped"
            d.error = f"source reports it doesn't support {symbol}/{interval}"
            return
        frame = source.fetch_candles(symbol, interval, start, end)
        d.latency_ms = int((time.time() - t0) * 1000)
        # `fetch_candles` returns CandleFrame; the rows live on .bars.
        bars = frame.bars if hasattr(frame, "bars") else frame
        d.rows_fetched = 0 if bars is None or bars.empty else int(len(bars))
        if d.rows_fetched > 0:
            d.status = "ok"
            d.earliest = str(bars["timestamp"].iloc[0])
            d.latest = str(bars["timestamp"].iloc[-1])
            d.sample = bars.tail(3)[["timestamp", "open", "high", "low", "close", "volume"]].astype(str).to_dict(orient="records")
        else:
            d.status = "error"
            d.error = "source returned 0 rows"
    except RuntimeError as exc:  # usually "no key" or a well-formed API error
        d.latency_ms = int((time.time() - t0) * 1000)
        msg = str(exc)
        d.status = "no_key" if ("needs an API key" in msg or "requires an API key" in msg) else "error"
        d.error = msg
    except Exception as exc:  # noqa: BLE001
        d.latency_ms = int((time.time() - t0) * 1000)
        d.status = "error"
        d.error = f"{type(exc).__name__}: {exc}"


@router.get("/diagnostics/sources")
def diagnose_sources(creds: CredsDep) -> dict[str, Any]:
    """Canary-probe every wired source. No DB writes — this just pings."""
    now = datetime.now(UTC)
    three_days = now - timedelta(days=3)
    week = now - timedelta(days=7)
    twenty_yr = now - timedelta(days=20 * 365)

    # Lazy imports keep the backend boot fast + let this endpoint degrade
    # gracefully when a source package isn't installed.
    from backend.services.sources.alphavantage_source import AlphaVantageSource
    from backend.services.sources.binance_source import BinanceSource
    from backend.services.sources.coinbase_source import CoinbaseSource
    from backend.services.sources.coingecko_source import CoinGeckoSource
    from backend.services.sources.cryptocompare_source import CryptoCompareSource
    from backend.services.sources.fred_source import FREDSource
    from backend.services.sources.hyperliquid_source import HyperliquidSource
    from backend.services.sources.yfinance_source import YFinanceSource

    out: list[SourceDiagnostic] = []

    # Crypto — canary BTC/1h last 3 days.
    for ctor, label in [
        (HyperliquidSource,       "Hyperliquid (native perps)"),
        (BinanceSource,           "Binance (spot)"),
        (CoinbaseSource,          "Coinbase Exchange"),
        (CoinGeckoSource,         "CoinGecko (free tier)"),
    ]:
        d = SourceDiagnostic(name=ctor.__name__.replace("Source", "").lower(),
                             label=label, canary="BTC 1h last 3 days")
        try:
            src = ctor()
        except Exception as exc:  # noqa: BLE001
            d.status = "error"
            d.error = f"constructor failed: {exc}"
            out.append(d)
            continue
        _probe_candles(src, "BTC", "1h", three_days, now, d)
        out.append(d)

    # CryptoCompare — needs credentials store for optional key.
    d = SourceDiagnostic(name="cryptocompare", label="CryptoCompare (deep history)",
                         canary="BTC 1h last 3 days")
    try:
        src = CryptoCompareSource(credentials=creds)
        _probe_candles(src, "BTC", "1h", three_days, now, d)
    except Exception as exc:  # noqa: BLE001
        d.status, d.error = "error", str(exc)
    out.append(d)

    # yfinance — canary AAPL/1d last week.
    d = SourceDiagnostic(name="yfinance", label="Yahoo Finance (yfinance)",
                         canary="AAPL 1d last 7 days")
    try:
        src = YFinanceSource()
        _probe_candles(src, "AAPL", "1d", week, now, d)
    except Exception as exc:  # noqa: BLE001
        d.status, d.error = "error", str(exc)
    out.append(d)

    # Alpha Vantage — requires user-stored key.
    d = SourceDiagnostic(name="alphavantage", label="Alpha Vantage (stocks/intraday)",
                         canary="AAPL 1d last 7 days (free tier last 100 bars)")
    try:
        src = AlphaVantageSource(credentials=creds)
        _probe_candles(src, "AAPL", "1d", week, now, d)
    except Exception as exc:  # noqa: BLE001
        d.status, d.error = "error", str(exc)
    out.append(d)

    # FRED — requires user-stored key.
    d = SourceDiagnostic(name="fred", label="FRED (Federal Reserve)",
                         canary="DGS10 (10Y Treasury) since 2005")
    try:
        src = FREDSource(credentials=creds)
        _probe_candles(src, "DGS10", "1d", twenty_yr, now, d)
    except Exception as exc:  # noqa: BLE001
        d.status, d.error = "error", str(exc)
    out.append(d)

    summary = {
        "total": len(out),
        "ok": sum(1 for d in out if d.status == "ok"),
        "error": sum(1 for d in out if d.status == "error"),
        "no_key": sum(1 for d in out if d.status == "no_key"),
        "skipped": sum(1 for d in out if d.status == "skipped"),
    }
    return {"summary": summary, "sources": [d.as_dict() for d in out]}


