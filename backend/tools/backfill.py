"""Backfill CLI: ``python -m backend.tools.backfill``

Assembles the default source router (Hyperliquid + Binance + Coinbase +
yfinance) and stitches history for a (symbol, interval) range into the
Parquet lake.

Example:
    python -m backend.tools.backfill --symbol BTC --interval 1h \\
        --from 2015-01-01 --to 2026-04-20

    python -m backend.tools.backfill --symbol xyz:TSLA --interval 1h \\
        --depth max

Exit codes:
    0 — success, bars written (or none needed).
    1 — source error and --allow-partial not set.
    2 — bad arguments.
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from backend.db.parquet_writer import append_ohlcv
from backend.db.paths import DEFAULT_DATA_ROOT
from backend.services.source_router import SourceRouter, SourceSlice
from backend.services.sources.base import CandleFrame
from backend.services.sources.alphavantage_source import AlphaVantageSource
from backend.services.sources.binance_source import BinanceSource
from backend.services.sources.coinbase_source import CoinbaseSource
from backend.services.sources.coingecko_source import CoinGeckoSource
from backend.services.sources.cryptocompare_source import CryptoCompareSource
from backend.services.sources.fred_source import FREDSource
from backend.services.sources.hyperliquid_source import HyperliquidSource
from backend.services.sources.yfinance_source import YFinanceSource

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackfillArgs:
    symbol: str
    interval: str
    start: datetime
    end: datetime
    depth: str  # "target" | "max"
    data_root: Path
    source: str | None  # None = auto, otherwise restrict to one named source
    allow_partial: bool
    testnet: bool


def build_default_router(
    *,
    testnet: bool = False,
    credentials: "Any | None" = None,
) -> SourceRouter:
    """Standard router: Hyperliquid primary + Binance / Coinbase / yfinance
    + the new keyed/key-optional sources (CryptoCompare, CoinGecko, FRED,
    Alpha Vantage) when a ``CredentialsStore`` is passed. Sources missing
    credentials gracefully fall through at plan time via their ``supports``
    / ``fetch_candles`` checks."""
    shared_http = httpx.Client(timeout=10.0)
    sources = [
        HyperliquidSource(testnet=testnet, http_client=shared_http),
        BinanceSource(http_client=shared_http),
        CoinbaseSource(http_client=shared_http),
        YFinanceSource(),
        # Crypto fallbacks — no key required for free tier.
        CryptoCompareSource(credentials=credentials),
        CoinGeckoSource(),
        # Macro + stock intraday — require user-provided keys.
        FREDSource(credentials=credentials),
        AlphaVantageSource(credentials=credentials),
    ]
    return SourceRouter(sources)


def run(
    args: BackfillArgs,
    *,
    router_factory: Callable[[], SourceRouter] = build_default_router,
    append_fn: Callable[[CandleFrame, Path], int] | None = None,
    progress_fn: Callable[[str], None] | None = None,
) -> int:
    """Execute a backfill. Returns total rows written (after dedupe)."""
    router = router_factory()
    plan = router.plan(args.symbol, args.interval, args.start, args.end)
    if not plan:
        _say(progress_fn, f"No source covers {args.symbol}/{args.interval} in the requested range.")
        return 0

    _say(progress_fn, f"Plan: {_describe_plan(plan)}")

    total_written = 0
    errors: list[tuple[str, str]] = []
    for slice_ in plan:
        _say(
            progress_fn,
            f"  [{slice_.source_name}] {slice_.start.isoformat()} → {slice_.end.isoformat()}",
        )
        try:
            frame = slice_.source.fetch_candles(
                args.symbol, args.interval, slice_.start, slice_.end
            )
        except Exception as exc:  # noqa: BLE001 — want to catch any adapter failure
            errors.append((slice_.source_name, str(exc)))
            continue

        if frame.is_empty:
            _say(progress_fn, f"    (empty response from {slice_.source_name})")
            continue

        if append_fn is None:
            n = append_ohlcv(frame, data_root=args.data_root)
        else:
            n = append_fn(frame, args.data_root)
        total_written += n
        _say(progress_fn, f"    wrote {n} rows (post-dedupe)")

    _say(progress_fn, f"Done. Total rows in lake for this symbol/interval: {total_written}")
    if errors:
        _say(progress_fn, f"Errors: {errors}")
        if not args.allow_partial:
            return -1  # caller translates to non-zero exit
    return total_written


# ── CLI glue ───────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> BackfillArgs:
    parser = argparse.ArgumentParser(
        prog="backend.tools.backfill",
        description="Stitch historical OHLCV for a (symbol, interval) into the Parquet lake.",
    )
    parser.add_argument("--symbol", required=True, help="e.g. BTC, ETH, xyz:TSLA, cash:GOLD")
    parser.add_argument(
        "--interval",
        required=True,
        choices=["1m", "5m", "15m", "1h", "4h", "1d"],
        help="Candle interval",
    )
    parser.add_argument(
        "--from",
        dest="start",
        default="2015-01-01",
        help="ISO start date (UTC). Default 2015-01-01.",
    )
    parser.add_argument(
        "--to",
        dest="end",
        default=None,
        help="ISO end date (UTC). Default = now.",
    )
    parser.add_argument(
        "--depth",
        choices=["target", "max"],
        default="target",
        help="Depth hint for planners. 'max' tries to stitch all sources.",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=DEFAULT_DATA_ROOT,
        help="Lake root directory (default: ./data).",
    )
    parser.add_argument(
        "--source",
        default=None,
        help="Restrict to a single source by name (hyperliquid, binance, coinbase, yfinance).",
    )
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Don't treat source errors as a non-zero exit.",
    )
    parser.add_argument(
        "--testnet",
        action="store_true",
        help="Use Hyperliquid testnet instead of mainnet.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print per-slice progress.",
    )

    ns = parser.parse_args(argv)

    start = _parse_iso_date(ns.start)
    end = _parse_iso_date(ns.end) if ns.end else datetime.now(UTC)
    if end <= start:
        parser.error("--to must be after --from")

    return BackfillArgs(
        symbol=ns.symbol,
        interval=ns.interval,
        start=start,
        end=end,
        depth=ns.depth,
        data_root=ns.data_root,
        source=ns.source,
        allow_partial=ns.allow_partial,
        testnet=ns.testnet,
    ), ns.verbose


def _parse_iso_date(value: str) -> datetime:
    # Accept 'YYYY-MM-DD' or full ISO. Force UTC.
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _describe_plan(plan: list[SourceSlice]) -> str:
    parts = []
    for s in plan:
        parts.append(
            f"{s.source_name}:{s.start.date().isoformat()}→{s.end.date().isoformat()}"
        )
    return " → ".join(parts)


def _say(progress_fn: Callable[[str], None] | None, msg: str) -> None:
    if progress_fn is not None:
        progress_fn(msg)
    else:
        print(msg, file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args, verbose = _parse_args(argv)
    progress = (lambda m: print(m, file=sys.stderr)) if verbose else None
    result = run(args, progress_fn=progress)
    return 0 if result >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
