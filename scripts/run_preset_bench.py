"""Backtest every preset (strategy, asset) pair and print a report card.

Writes to ``data/preset_bench.csv`` + stdout. Pairs that clear the user's
target win-rate go into ``data/preset_bench_winners.csv`` for conversion
into preset slots.

Run from the repo root (with the .venv active):
    .venv/bin/python -m scripts.run_preset_bench

The ``candle_query`` helper pulls from the local DuckDB catalog (which sits
on top of the Parquet lake). If an asset doesn't have enough history in
the lake, it fetches synchronously via the backfill service first.
"""
from __future__ import annotations

import csv
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from backend.db.duckdb_catalog import DuckDBCatalog
from backend.db.paths import DEFAULT_DATA_ROOT
from backend.services.backtest.engine import BacktestConfig, BacktestEngine
from backend.tools.backfill import BackfillArgs
from backend.tools.backfill import run as run_backfill

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Target WR — the user asked for 75% so report which pairs clear it.
TARGET_WR = 0.75

# ── Strategies to test ─────────────────────────────────────────────
STRATEGIES = [
    ("connors_rsi2",      {}),
    ("bb_fade",           {}),
    ("keltner_reversion", {}),
    ("williams_mean_rev", {}),
    ("gap_fill",          {}),
]

# ── Assets ─────────────────────────────────────────────────────────
# (symbol, interval, lookback_years) — interval + depth picked per asset.
# Crypto on 1h gives us more trades; equities/commodities on 1d to match
# how yfinance serves history.
ASSETS = [
    # Crypto on daily — mean-reversion strategies need lower noise. The
    # 1h variant is also worth running, but daily is the proven timeframe
    # for Connors-style + Keltner setups.
    ("BTC",   "1d", 10),
    ("ETH",   "1d", 7),
    ("SPY",   "1d", 20),   # S&P 500 proxy (Hyperliquid xyz:SP500 maps to SPY for backtest)
    ("QQQ",   "1d", 20),   # Nasdaq-100 proxy (HL xyz:XYZ100 maps to QQQ)
    ("TSLA",  "1d", 15),
    ("GC=F",  "1d", 20),   # Gold front-month futures (HL cash:GOLD)
    ("CL=F",  "1d", 15),   # WTI front-month futures (HL cash:OIL)
]


def _query(catalog: DuckDBCatalog, symbol: str, interval: str,
           start: datetime, end: datetime):
    with catalog:
        return catalog.query_candles(symbol, interval, start, end)


def _ensure_data(symbol: str, interval: str, start: datetime, end: datetime) -> None:
    """Trigger a synchronous backfill if the lake is too thin."""
    try:
        run_backfill(BackfillArgs(
            symbol=symbol, interval=interval, start=start, end=end,
            depth="target", data_root=DEFAULT_DATA_ROOT, source=None,
            allow_partial=True, testnet=False,
        ), progress_fn=lambda m: logger.info("    %s", m[:100]))
    except Exception as exc:  # noqa: BLE001
        logger.warning("backfill for %s/%s partial: %s", symbol, interval, exc)


def _fmt_pct(v: float) -> str:
    return f"{v * 100:5.1f}%"


def _fmt_sharpe(v: float) -> str:
    return f"{v:5.2f}"


def main() -> int:
    out_path = DEFAULT_DATA_ROOT / "preset_bench.csv"
    winners_path = DEFAULT_DATA_ROOT / "preset_bench_winners.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    catalog = DuckDBCatalog(DEFAULT_DATA_ROOT)

    rows = []
    for (symbol, interval, years) in ASSETS:
        end = datetime.now(UTC)
        start = end - timedelta(days=years * 365)
        logger.info("Loading %s/%s (%dy)", symbol, interval, years)
        _ensure_data(symbol, interval, start, end)

        for (strategy, params) in STRATEGIES:
            cfg = BacktestConfig(
                symbol=symbol,
                interval=interval,
                strategy=strategy,
                strategy_params=params,
                stop_loss_pct=2.5,
                take_profit_pct=4.0,
                size_usd=1000.0,
                starting_cash=10_000.0,
                slippage_bps=2.0,
                fee_bps=5.0,
                funding_bps_per_bar=0.0,
                bar_lookback=250,   # all 5 strategies need up to 200 bars of warmup
            )
            engine = BacktestEngine(
                candle_query=lambda s, i, f, t: _query(catalog, s, i, f, t),
            )
            try:
                result = engine.run(cfg, start, end)
            except Exception as exc:  # noqa: BLE001
                logger.warning("  %s on %s: FAILED — %s", strategy, symbol, exc)
                rows.append({
                    "strategy": strategy, "symbol": symbol, "interval": interval,
                    "trades": 0, "win_rate": None, "sharpe": None,
                    "max_dd_pct": None, "return_pct": None,
                    "expectancy": None, "error": str(exc)[:120],
                })
                continue

            metrics = result.metrics
            tc = int(metrics.get("trade_count", 0) or 0)
            rows.append({
                "strategy": strategy,
                "symbol": symbol,
                "interval": interval,
                "trades": tc,
                "win_rate": metrics.get("win_rate"),
                "sharpe": metrics.get("sharpe"),
                "max_dd_pct": metrics.get("max_drawdown_pct"),
                "return_pct": metrics.get("total_return_pct"),
                "expectancy": metrics.get("expectancy"),
                "error": "",
            })
            logger.info(
                "  %-20s %s/%s  trades=%3d  WR=%s  Sharpe=%s  DD=%s  Ret=%s",
                strategy, symbol, interval, tc,
                _fmt_pct(metrics.get("win_rate") or 0.0),
                _fmt_sharpe(metrics.get("sharpe") or 0.0),
                _fmt_pct((metrics.get("max_drawdown_pct") or 0.0) / 100),
                _fmt_pct((metrics.get("total_return_pct") or 0.0) / 100),
            )

    # ── write CSV ────────────────────────────────────────────────
    fieldnames = ["strategy", "symbol", "interval", "trades", "win_rate",
                  "sharpe", "max_dd_pct", "return_pct", "expectancy", "error"]
    with out_path.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    winners = [r for r in rows
               if r.get("win_rate") is not None
               and r["win_rate"] >= TARGET_WR
               and r["trades"] >= 20]
    with winners_path.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(winners)

    # ── report card ──────────────────────────────────────────────
    print()
    print("=" * 100)
    print(f"{'Strategy':<22} {'Asset':<8} {'TF':<4} {'#':>5} {'WR':>7} {'Sharpe':>7} {'MaxDD':>8} {'Return':>8}")
    print("-" * 100)
    for r in rows:
        wr = r.get("win_rate")
        if wr is None:
            print(f"{r['strategy']:<22} {r['symbol']:<8} {r['interval']:<4}  FAILED  {r['error']}")
            continue
        mark = " ✅" if wr >= TARGET_WR and r["trades"] >= 20 else ""
        print(
            f"{r['strategy']:<22} {r['symbol']:<8} {r['interval']:<4} "
            f"{r['trades']:>5} {wr*100:>6.1f}% {(r['sharpe'] or 0):>6.2f} "
            f"{(r.get('max_dd_pct') or 0):>7.2f}% {(r.get('return_pct') or 0):>7.2f}%{mark}"
        )
    print("=" * 100)
    print(f"Winners (WR >= {TARGET_WR*100:.0f}% with >= 20 trades): {len(winners)}")
    print(f"Full report: {out_path}")
    print(f"Winners CSV: {winners_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
