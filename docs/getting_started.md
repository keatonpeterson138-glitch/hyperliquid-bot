# Getting Started

This is the user-facing quickstart for the Hyperliquid Bot desktop app (v1.0).
For architecture internals, see [`../internal_docs/OVERHAUL_PLAN.md`](../internal_docs/OVERHAUL_PLAN.md).

## Install

Pick your platform:

- **Windows** — download `hyperliquid-bot_<version>_x64_en-US.msi`, run it.
- **macOS** — download `hyperliquid-bot_<version>_universal.dmg`, drag to Applications.
- **Linux** — download `hyperliquid-bot_<version>_amd64.AppImage`, `chmod +x`, run.

On first launch the app walks you through:

1. **Vault setup.** Import your Hyperliquid private key. It's encrypted and stored in the OS keychain — never written to disk in plaintext.
2. **Historical data bootstrap.** ~7 GB pulled from Hyperliquid, Binance, Coinbase, and yfinance. Runs in the background, 30–90 min on a typical connection. Resume-safe — if you close the app it picks up where it left off.
3. **Testnet toggle.** Default on. Flip it off in Settings → Exchange when you're ready to risk real money.

## First trade (testnet)

1. Open **Charts**, pick BTC 1h.
2. Click **+ Long** in the markup toolbar, enter an entry + SL + TP.
3. Click **Arm** in the drawing list. Enter size (USD) + leverage. Confirm.
4. The bracket lands on testnet; the markup state flips to `pending`, then `working` once filled.
5. **Drag the SL or TP line on the chart** — the exchange order modifies to match within 250ms.
6. **Ctrl+Shift+K** flattens everything and disables all slots.

## Deploying a strategy as a slot

1. **Slots → New slot.** Pick `ema_crossover`, BTC, 1h.
2. Set size, leverage, SL%, TP%. Optionally enable shadow mode (runs in parallel on testnet for comparison, no real capital).
3. Save. The slot runs until you disable it or the kill switch flips.

## Backtesting

1. **Backtest Lab.** Pick strategy + symbol + range.
2. **Run**. Live equity curve streams via WebSocket; metrics render as the run completes.
3. **Parameter sweep.** Add a grid (`{"fast": [5, 10, 20]}`) — returns a ranked table.
4. **Monte Carlo.** Shuffles trade order N times, reports 5/50/95% drawdown + ending-equity percentiles.
5. **Walk-forward.** Rolling train/test windows; OOS-only metrics aggregate across folds.

## Training an ML strategy

1. **Training Lab.** Pick family (`logreg` / `xgb_cls`), feature set (`core_v1`), labeler (`triple_barrier`), symbol + range + CV config (purged k-fold with embargo).
2. **Train.** Progress streams live. Model card renders OOS metrics + feature importance on completion.
3. **Promote to slot.** The model is now a first-class strategy — deploy it via the slot manager with `get_strategy("ml:<model_id>")` behind the scenes.

## Keyboard shortcuts

| Key | Action |
|---|---|
| `Ctrl+K` | Command palette |
| `Ctrl+,` | Settings |
| `Ctrl+Shift+K` | Kill switch (flatten + cancel + disable everything) |
| `Ctrl+S` | Save layout |
| `Ctrl+F` | Symbol search |
| `Ctrl+B` | Toggle sidebar |
| `Ctrl+.` | Toggle inspector |

## Troubleshooting

- **"Outcome discovery is not wired yet"** — unlock the vault; UniverseManager needs exchange creds to list HIP-4 markets.
- **WebSocket keeps reconnecting** — check that `backend` is running (`data/logs/backend.log`). In prod builds this is a sidecar managed by Tauri; dev builds run it yourself: `uvicorn backend.main:app --port 8787`.
- **Aggregate exposure cap exceeded** — Settings → Risk defaults → cap. Or free up capacity by closing positions.
- **No bars for <symbol>** — run the first-run bootstrap, or `python -m backend.tools.backfill --symbol <sym>`.

## Where things live

| Path | What |
|---|---|
| `data/app.db` | SQLite state (markets, slots, audit, markups, orders, models) |
| `data/duckdb/catalog.db` | DuckDB warm catalog for lake reads |
| `data/parquet/ohlcv/` | Raw candle lake (Hive-partitioned) |
| `data/parquet/outcomes/` | HIP-4 tick tape |
| `data/parquet/features/` | Computed feature store |
| `data/models/` | Trained ML artefacts |
| `data/backtests/` | Backtest snapshots |
| `data/logs/backend.log` | Rotating backend log |
| `data/settings.json` | App settings |
| `data/notes/` | Research notebook files |

## Learn more

- [Architecture guide](../internal_docs/OVERHAUL_PLAN.md)
- [Phase rollout plan](../internal_docs/PHASE_5p5_TO_12_PLAN.md)
- [Changelog](../internal_docs/Changelog.txt)
