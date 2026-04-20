"""Bootstrap the Parquet lake — ``python -m backend.tools.bootstrap_lake``.

Wraps ``UniverseManager.refresh()`` + the per-symbol backfill with
checkpointed resume. Intended to be run once at install time (or from
the first-run wizard) to fill historical OHLCV + outcome tape for every
active market, per the depth targets in ``OVERHAUL_PLAN.md §6.1``.

Checkpoints live in ``app.db.bootstrap_progress`` so rerunning picks up
where it left off and skips completed (symbol, interval, year) tuples.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from backend.db.app_db import AppDB
from backend.services.universe_manager import UniverseManager

logger = logging.getLogger(__name__)

# Depth targets from OVERHAUL_PLAN §6.1.
DEFAULT_DEPTHS = {
    "1d":  10 * 365,   # 10 years
    "1h":  7 * 365,    # 7 years
    "15m": 3 * 365,    # 3 years
    "5m":  2 * 365,    # 2 years
    "1m":  365,        # 1 year
}


@dataclass
class BootstrapPlanItem:
    symbol: str
    interval: str
    from_ts: datetime
    to_ts: datetime


def ensure_progress_table(db: AppDB) -> None:
    with db.transaction() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bootstrap_progress (
                symbol   TEXT NOT NULL,
                interval TEXT NOT NULL,
                year     INTEGER NOT NULL,
                status   TEXT NOT NULL,      -- 'complete' | 'failed'
                bars_loaded INTEGER DEFAULT 0,
                error    TEXT,
                completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (symbol, interval, year)
            )
            """
        )


def completed_slices(db: AppDB) -> set[tuple[str, str, int]]:
    rows = db.fetchall(
        "SELECT symbol, interval, year FROM bootstrap_progress WHERE status = 'complete'"
    )
    return {(r["symbol"], r["interval"], int(r["year"])) for r in rows}


def mark_slice(
    db: AppDB,
    symbol: str,
    interval: str,
    year: int,
    *,
    status: str,
    bars_loaded: int = 0,
    error: str | None = None,
) -> None:
    with db.transaction() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO bootstrap_progress
                (symbol, interval, year, status, bars_loaded, error, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (symbol, interval, year, status, bars_loaded, error, datetime.now(UTC)),
        )


def plan(
    universe: UniverseManager,
    *,
    intervals: Iterable[str] = ("1d", "1h", "15m", "5m"),
    max_symbols: int | None = None,
    now: datetime | None = None,
) -> list[BootstrapPlanItem]:
    """Cross-product of universe × intervals × depth targets. One item per
    (symbol, interval) covering the full depth range — the actual
    per-year slicing happens in ``run_one``."""
    now = now or datetime.now(UTC)
    markets = universe.list_markets(kind="perp", active_only=True)
    if max_symbols:
        markets = markets[:max_symbols]

    out: list[BootstrapPlanItem] = []
    for m in markets:
        sym = m["symbol"]
        for interval in intervals:
            depth_days = DEFAULT_DEPTHS.get(interval, 365)
            out.append(BootstrapPlanItem(
                symbol=sym,
                interval=interval,
                from_ts=now - timedelta(days=depth_days),
                to_ts=now,
            ))
    return out


def run_one(
    item: BootstrapPlanItem,
    db: AppDB,
    *,
    backfill_fn,
    on_slice_done: callable | None = None,  # type: ignore[assignment]
    throttle_seconds: float = 0.0,
) -> dict:
    """Backfill a single (symbol, interval) split by year so progress
    checkpoints are fine-grained."""
    start_year = item.from_ts.year
    end_year = item.to_ts.year
    done = completed_slices(db)
    total_bars = 0
    year_results: list[dict] = []

    for year in range(start_year, end_year + 1):
        if (item.symbol, item.interval, year) in done:
            year_results.append({"year": year, "skipped": True})
            continue
        year_start = max(item.from_ts, datetime(year, 1, 1, tzinfo=UTC))
        year_end = min(item.to_ts, datetime(year + 1, 1, 1, tzinfo=UTC))
        try:
            result = backfill_fn(
                symbol=item.symbol,
                interval=item.interval,
                from_ts=year_start,
                to_ts=year_end,
            )
            bars = int(result.get("bars_written", 0) or 0)
            total_bars += bars
            mark_slice(db, item.symbol, item.interval, year, status="complete", bars_loaded=bars)
            year_results.append({"year": year, "bars_loaded": bars})
        except Exception as exc:  # noqa: BLE001
            mark_slice(db, item.symbol, item.interval, year, status="failed", error=str(exc))
            year_results.append({"year": year, "error": str(exc)})
        if throttle_seconds > 0:
            time.sleep(throttle_seconds)
        if on_slice_done is not None:
            on_slice_done(item.symbol, item.interval, year, year_results[-1])

    return {
        "symbol": item.symbol,
        "interval": item.interval,
        "total_bars": total_bars,
        "years": year_results,
    }


def run(
    plan_items: list[BootstrapPlanItem],
    db: AppDB,
    *,
    backfill_fn,
    throttle_seconds: float = 0.0,
    on_slice_done: callable | None = None,  # type: ignore[assignment]
) -> dict:
    summary: list[dict] = []
    for item in plan_items:
        summary.append(run_one(
            item, db,
            backfill_fn=backfill_fn,
            throttle_seconds=throttle_seconds,
            on_slice_done=on_slice_done,
        ))
    return {"plan_size": len(plan_items), "results": summary}


def _default_backfill_fn(*, symbol: str, interval: str, from_ts: datetime, to_ts: datetime) -> dict:
    """Wrap the existing backfill CLI logic. Lazy-imports to avoid a
    hard dep at bootstrap-module import time (useful for tests)."""
    from backend.tools.backfill import run_backfill
    return run_backfill(
        symbol=symbol,
        interval=interval,
        from_ts=from_ts,
        to_ts=to_ts,
        data_root=Path("data"),
        allow_partial=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="backend.tools.bootstrap_lake")
    parser.add_argument("--intervals", default="1d,1h,15m,5m",
                        help="Comma-separated interval tiers (default: 1d,1h,15m,5m)")
    parser.add_argument("--max-symbols", type=int, default=None,
                        help="Cap the symbol count (useful for smoke runs)")
    parser.add_argument("--throttle-seconds", type=float, default=0.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db = AppDB()
    ensure_progress_table(db)
    universe = UniverseManager(db)
    universe.refresh()
    items = plan(
        universe,
        intervals=tuple(args.intervals.split(",")),
        max_symbols=args.max_symbols,
    )
    logger.info("Plan: %d (symbol, interval) slices", len(items))
    if args.dry_run:
        for it in items[:20]:
            print(f"  {it.symbol:15s} {it.interval:5s} {it.from_ts.date()} → {it.to_ts.date()}")
        if len(items) > 20:
            print(f"  ... and {len(items) - 20} more")
        return 0

    summary = run(
        items, db,
        backfill_fn=_default_backfill_fn,
        throttle_seconds=args.throttle_seconds,
        on_slice_done=lambda sym, iv, yr, r: logger.info(
            "%s %s %d → %s", sym, iv, yr, r.get("bars_loaded") or r.get("error") or "skipped"
        ),
    )
    total = sum(r["total_bars"] for r in summary["results"])
    logger.info("bootstrap done — %d bars across %d (symbol, interval) slices", total, summary["plan_size"])
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
