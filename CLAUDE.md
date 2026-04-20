# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) and other AI assistants when working with code in this repository.

## Project Overview

Hyperliquid Trading Bot — automated perpetual-futures + prediction-market trading bot for the Hyperliquid exchange. Supports Hyperliquid native perps (BTC, ETH, SOL, HYPE, alts), HIP-3 builder-deployed perps (stocks via trade.xyz — NVDA/TSLA/AAPL/MSFT/AMZN/etc., indices — SP500/XYZ100, commodities — gold/silver/crude/corn/wheat, FX), and HIP-4 outcome contracts (prediction markets, curated canonical markets on testnet as of April 2026).

The project is mid-**platform overhaul** — see `internal_docs/OVERHAUL_PLAN.md` for the full v1 architecture. This doc describes **what exists today** and flags what is **planned / in-progress** so AI tools can navigate correctly.

## Commands

- `python bot.py` — headless CLI trading loop (single slot, uses `.env` config). Deprecated after v0.1 but still works.
- `python dashboard.py` — Tkinter desktop dashboard (current primary UI; replaced in overhaul).
- `python test_setup.py` — one-off sanity check that credentials are valid and exchange is reachable.
- `python test_trade.py` — one-off round-trip trade test (testnet-only).
- `python -m scripts.testnet_faucet` — request testnet funds.
- `python check_position.py` — quick CLI position inspector.
- `python debug_balance.py` / `python debug_unified.py` — debug helpers.
- `python discover_markets.py` — enumerate markets from Hyperliquid.

**Planned (post-Phase 0 / Phase 2):**
- `uvicorn backend.main:app` — FastAPI backend service (v1 architecture).
- `cd ui && npm run dev` — Tauri + Vite dev server (v1 UI).
- `cd ui && npm run tauri:build` — produce desktop installer.
- `pytest` — unit test suite (no suite exists yet; added in Phase 0).

## Architecture

### Current (as-shipped)

**Two entry points:**
- `bot.py` — minimal CLI loop. One symbol, one strategy, one position. Validates config → sets leverage → polls every `LOOP_INTERVAL_SEC`: risk-exit check → fetch candles → run strategy → execute signal.
- `dashboard.py` — **2,431-line Tkinter monolith**. Assembles the GUI, connects to the trading engine, runs the loop. Extraction of the engine portion into a headless `TradeEngine` is Phase 0 of the overhaul.

**Current layout:**

```
hyperliquid-bot/
├── bot.py, dashboard.py           ← entry points
├── config.py                       ← .env loader + multi-slot parser (5 slots)
├── core/                           ← exchange + infrastructure
├── strategies/                     ← strategy plugins
├── gui/                            ← Tkinter tabs (~3000 LOC)
├── scripts/                        ← one-off utilities
├── test_setup.py, test_trade.py    ← ad-hoc manual test scripts
└── internal_docs/                  ← design docs
```

### Key Directories

- **`core/`** — Exchange-facing and infrastructure code. No strategy logic.
  - `exchange.py` (544 LOC) — Hyperliquid SDK wrapper. `HyperliquidClient` handles account init, market price, candle fetch, position queries, order placement/modification/cancellation, leverage setting, close-all. Supports native perps + HIP-3 via `dex=` parameter.
  - `market_data.py` (118 LOC) — Candle fetcher over Info API. Returns DataFrames.
  - `risk_manager.py` (139 LOC) — SL/TP thresholds, daily loss cap, max open positions. Stateful.
  - `news_monitor.py` (495 LOC) — RSS/API news feed poller with keyword filters.
  - `email_notifier.py` (168 LOC) — SMTP alerts.
  - `telegram_notifier.py` (345 LOC) — Telegram Bot API alerts.
  - `outcome_client.py` (585 LOC) — HIP-4 outcome contract client: list markets, fetch tape, place outcome orders.
  - `outcome_monitor.py` (557 LOC) — Poll outcome markets, emit events on price/probability changes.
  - `pricing_model.py` (648 LOC) — Theoretical outcome pricing (Bayesian / base-rate models). Produces fair-value vs market-implied probabilities for edge detection.

- **`strategies/`** — Strategy plugins extending `BaseStrategy`.
  - `base.py` — `BaseStrategy` abstract class + `Signal`/`SignalType` data types. **The contract every strategy must honor: `analyze(df, current_position) -> Signal`.** See §8 of `internal_docs/Design.md`.
  - `factory.py` — `get_strategy(name, **params)` registry. Extension point for new strategies.
  - `ema_crossover.py`, `rsi_mean_reversion.py`, `breakout.py` — classic TA strategies.
  - `funding_dip.py` — funding-rate arbitrage for perps.
  - `outcome_arb.py` (665 LOC) — HIP-4 prediction-market arbitrage.

- **`gui/`** — Tkinter UI tabs (deprecated in overhaul). Each file is one tab or shared component.
  - `dashboard_tab.py` — live P&L + positions.
  - `predictions_tab.py` (638 LOC) — HIP-4 market board + detail.
  - `news_tab.py`, `settings_tab.py`, `log_tab.py`, `help_tab.py` — secondary tabs.
  - `sidebar.py`, `components.py`, `chart_widget.py`, `theme.py` — shared UI primitives.

- **`scripts/`** — `testnet_faucet.py` — request test funds. Add new one-off ops scripts here.

- **`internal_docs/`** — Design + planning docs (this dir).
  - `OVERHAUL_PLAN.md` — **primary reference for the v1 architecture.**
  - `Design.md` — product vision + architecture summary, numbered sections.
  - `Changelog.txt` — append-only change log.

- **`todo/`** — Status + phase tracking.
  - `path_to_v1.md` — 12-phase rollout tracker with 🔴/🟡/🟢 status per phase.

### Configuration

`config.py` loads from `.env` via `python-dotenv`. Key surfaces:

- **Credentials** — `PRIVATE_KEY`, `WALLET_ADDRESS`, `USE_TESTNET`. **Will move to OS keychain in Phase 2** — do not commit keys.
- **Market selection** — `DEX` (`''` = native, `'cash'` / `'xyz'` = HIP-3 dexes), `SYMBOL`. HIP-3 symbols use `dex:COIN` format (`cash:GOLD`, `xyz:TSLA`).
- **Trading params** — `POSITION_SIZE_USD`, `MAX_LEVERAGE`, `STRATEGY`, `CANDLE_INTERVAL`, `LOOP_INTERVAL_SEC`.
- **Risk** — `STOP_LOSS_PCT`, `TAKE_PROFIT_PCT`, `MAX_OPEN_POSITIONS`, `MAX_DAILY_LOSS_USD`.
- **Timeframe presets** — `TIMEFRAME_DEFAULTS` table (1m scalp → 1d position) gives recommended SL/TP/leverage per interval.
- **Multi-slot** — `SLOT_1..SLOT_5` pipe-separated strings. Parsed into `POSITION_SLOTS[]` by `Config._parse_slots()`. Serialized back via `Config.slot_to_env(slot)`. Fields per slot: `symbol|interval|strategy|sl|tp|leverage|enabled|size_usd|strategy_params_json|trailing_sl|mtf_enabled|regime_filter|atr_stops|loss_cooldown|volume_confirm|rsi_guard|rsi_guard_low|rsi_guard_high`.
- **Notifications** — `EMAIL_*`, `TELEGRAM_*`.

### Strategy Contract

Every strategy implements `BaseStrategy.analyze(df, current_position) -> Signal`. Inputs:

- `df` — OHLCV DataFrame with columns `[open, high, low, close, volume]`, indexed by timestamp. Enough lookback for the strategy's longest indicator.
- `current_position` — `'LONG'`, `'SHORT'`, or `None`.

Return a `Signal(signal_type: SignalType, strength: float, reason: str)`. `SignalType` is `LONG | SHORT | CLOSE_LONG | CLOSE_SHORT | HOLD`. `strength` is `0.0–1.0`.

This contract is stable. Backtest, shadow mode, and live trading all invoke strategies via this same signature.

### Hyperliquid Market Universe

As of April 2026 mainnet:

- **Native perps:** ~100 crypto assets (BTC, ETH, SOL, HYPE, and the long tail).
- **HIP-3 perps** (launched Oct 2025 via trade.xyz and similar deployers):
  - Stocks: NVDA, TSLA, AAPL, MSFT, GOOGL, AMZN, META, HOOD, INTC, PLTR, COIN, NFLX, MSTR, AMD, TSM.
  - Indices: SP500 (S&P Dow Jones-licensed, March 2026, 50× leverage), XYZ100 (Nasdaq-100 synthetic).
  - Commodities: gold, silver (COMEX-benchmarked), crude oil, corn, wheat.
  - FX pairs.
- **HIP-4 outcome contracts** (binary / bounded prediction markets): testnet live Feb 2026, mainnet pending, curated canonical first.

The v1 architecture discovers markets dynamically via `UniverseManager` (Phase 2). No hardcoded asset list.

### Risk Management

`core/risk_manager.py` currently tracks:
- Daily P&L vs `MAX_DAILY_LOSS_USD` — trips a `can_trade()` gate.
- Max open positions vs `MAX_OPEN_POSITIONS` — blocks `can_open_position()`.
- Per-position SL/TP check via `check_position_exit(entry, current, is_long)`.

**Planned in Phase 2 + 11** (see `internal_docs/OVERHAUL_PLAN.md` §13):
- OS keychain for private key storage (Tauri `keyring` plugin).
- Kill switch — global shortcut + always-visible button → flatten-all + cancel-all + disable slots.
- Aggregate exposure cap across slots.
- Confirmation modals above configurable $ and % thresholds.
- Append-only audit log table (SQLite).
- Optional testnet shadow mode — every live slot runs a parallel testnet copy, divergence alerts.

## Overhaul Status (Current Wave)

The project is pivoting from a Tkinter monolith to a **Tauri + React + FastAPI-sidecar** desktop app with Parquet + DuckDB storage, ML training, and analog/pattern search.

**Read first for any v1 work:** `internal_docs/OVERHAUL_PLAN.md` (1000+ lines, 18 sections).

**Phase tracker:** `todo/path_to_v1.md`.

Phases (see `OVERHAUL_PLAN.md` §4 for full detail):

| Phase | Deliverable | Ship |
|---|---|---|
| 0 | Foundation (engine extraction, repo layout, CI) | — |
| 1 | Data platform (Parquet + DuckDB, multi-source backfill) | — |
| 2 | Backend + trade engine + safety scaffolding | — |
| 3 | Tauri UI shell + OS keychain | — |
| 4 | Chart workspace | 🎯 v0.1 |
| 5 | Markup + chart-to-order | 🎯 v0.2 |
| 6 | HIP-4 outcome workspace | 🎯 v0.3 |
| 7 | Backtest engine | — |
| 8 | Research workbench | — |
| 9 | Analog / pattern search | 🎯 v0.4 |
| 10 | ML training pipeline | — |
| 11 | Slots 2.0 + hardening polish | — |
| 12 | Ship polish | 🎯 v1.0 |

## Conventions

- **No private keys in code, .env committed, or logs.** `.env` is in `.gitignore`. Keys move to OS keychain in Phase 2.
- **Strategy contract is stable** — `analyze(df, current_position) -> Signal`. Don't change the signature without updating every consumer + backtest engine.
- **Strategies must be stateless** between `analyze()` calls (or explicitly document any state — e.g., `outcome_arb` maintains a market-state cache). Backtest replays history; stateful strategies that depend on wall-clock time break.
- **Connected modules (`core/`)** are reusable. **New app code** lives in `backend/` (Phase 0+) — does not go in `dashboard.py` or `bot.py`.
- **Load combinations, fee schedules, market params** should be database-driven, not hardcoded. Matches the StruxDraft convention of "no hardcoded fallbacks."
- **HIP-4 outcomes are first-class v1 features**, not an afterthought. Any slot-manager / backtest / ML work should handle `PerpSlot` and `OutcomeSlot` uniformly via a `SlotRunner` interface.
- **Comments should explain WHY when non-obvious.** Don't narrate WHAT the code does — code + test names do that. Never write multi-paragraph docstrings or "added for feature X" comments.
- **Changelog discipline** — after any meaningful change, append to `internal_docs/Changelog.txt` with today's date, file list, and 1–3 sentences of intent. Never edit prior entries.

## Testing

**Current:** No real test suite. `test_setup.py` and `test_trade.py` are one-off manual scripts.

**Planned (Phase 0):** `pytest` under `tests/` mirroring the source layout:
- `tests/unit/core/` — exchange/market-data/risk mocked tests.
- `tests/unit/strategies/` — golden-signal tests per strategy (OHLCV fixture → expected Signal stream). Gate merges on no-drift.
- `tests/unit/backend/` — API + services (Phase 2+).
- `tests/integration/` — end-to-end bot loops against a mocked exchange.
- `tests/e2e/` — Playwright against the Tauri UI (Phase 3+).

## Related Docs

- `internal_docs/OVERHAUL_PLAN.md` — **the** reference for v1 architecture and rollout.
- `internal_docs/Design.md` — product vision + architecture summary, numbered sections for easy reference.
- `internal_docs/Changelog.txt` — append-only change log.
- `todo/path_to_v1.md` — phase-by-phase status tracker.
- `README.md` — user-facing overview and quickstart.
