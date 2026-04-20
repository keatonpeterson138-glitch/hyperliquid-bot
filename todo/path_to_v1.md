# Path to v1.0

The 12-phase rollout from the current Tkinter monolith to the Tauri + React + FastAPI desktop app described in [`../internal_docs/OVERHAUL_PLAN.md`](../internal_docs/OVERHAUL_PLAN.md). Each phase is a tracked initiative — not a single PR — and produces a user-visible build at the 🎯 milestones.

Status legend: 🔴 not started · 🟡 in progress · 🟢 done

_Last audited: 2026-04-20._

---

## Phase 0 — 🟡 Foundation (1 week)

**Goal:** Clean base for everything else; `bot.py` still works; `dashboard.py` keeps running until Phase 3 replaces it.

**Tasks**

- [ ] Split `dashboard.py` (2,431 LOC Tkinter monolith) into `engine.py` + `state.py` + `view.py`. The engine portion becomes the headless `TradeEngine` consumed by both `bot.py` and the v1 backend.
- [ ] Create `backend/` package (`api/`, `services/`, `models/`, `db/`, `main.py`) with FastAPI skeleton.
- [ ] Create `ui/` Tauri + React + Vite + TypeScript project skeleton.
- [x] Add dev/test deps to `requirements.txt`: `pytest>=8.0.0`, `pytest-asyncio>=0.23.0`, `ruff>=0.5.0`. Remaining v1 deps (`fastapi`, `uvicorn`, `duckdb`, `pyarrow`, `sqlalchemy`, `alembic`, `joblib`, `xgboost`, `scikit-learn`, `faiss-cpu`, `dtaidistance`, `cryptography`, `keyring`, `httpx`) to be added with the phases that need them.
- [x] Add `pyproject.toml` with `pytest` + `ruff` config (mypy deferred until type-hint pass).
- [x] Add `.github/workflows/ci.yml` — `ruff check` + `pytest -v` on push/PR.
- [x] Create `tests/` directory scaffolding mirroring source layout.
- [x] Land golden-signal tests per strategy (33 tests covering ema_crossover / rsi_mean_reversion / breakout / funding_dip / factory). Gate the merge pipeline on no-drift via CI. `outcome_arb` deferred (network dependency).

**Blocks:** Phase 1+ (data platform needs the `backend/` scaffolding).

---

## Phase 1 — 🔴 Data Platform (2 weeks)

**Goal:** Pull, store, query historical OHLCV + outcome tapes for the full Hyperliquid universe, stitched across multiple sources for maximum depth.

**Tasks**

- [ ] Source adapters: `HyperliquidSource`, `BinanceSource`, `CoinbaseSource`, `CryptoCompareSource`, `YFinanceSource` (+ optional `PolygonSource`).
- [ ] `DataSource` protocol + `SourceRouter.plan(symbol, interval, start, end)` returning stitched `(source, slice)` tuples.
- [ ] Parquet writer with Hive partitioning: `data/parquet/ohlcv/symbol=<s>/interval=<i>/year=<y>/part-000.parquet`.
- [ ] DuckDB catalog: `data/duckdb/catalog.db` with views over Parquet files + partition pruning.
- [ ] Outcome tape storage: `data/parquet/outcomes/market_id=<id>/year=<y>/part-000.parquet`.
- [ ] Backfill CLI: `python -m backend.tools.backfill --target all --depth max`.
- [ ] Incremental updater daemon: tail latest bar into Parquet every interval.
- [ ] Cross-validate mode: pull from two sources in parallel, alert on divergence > threshold.
- [ ] REST: `GET /candles`, `GET /catalog`, `POST /backfill`, WS `/stream/backfill/{job_id}`.
- [ ] Dedupe key: `(symbol, interval, timestamp, source)`. Last-write-wins per ingestion.

**Depth targets** (see `OVERHAUL_PLAN.md` §6.1):

- 1d: 10+ years · 1h: 5–7 years · 15m: 3 years · 5m: 2 years · 1m: rolling 6–12 months.

---

## Phase 2 — 🔴 Backend + Trade Engine + Safety Scaffolding (2 weeks)

**Goal:** Every capability the current `dashboard.py` has, reachable over HTTP/WS; mainnet hardening scaffolded; no UI change yet.

**Tasks**

- [ ] `UniverseManager.refresh()` — dynamic market discovery via Hyperliquid SDK. Persist to SQLite `markets` + `market_tags` tables.
- [ ] `TradeEngine` — N-slot runner in a thread pool; emits `tick`, `candle_close`, `signal`, `order_filled`, `position_update`, `pnl_update`, `log` events on WS.
- [ ] `KeyVault` — OS keyring storage via `keyring` Python lib; unlock-on-start; `.env` fallback only in `DEV_MODE=1`.
- [ ] `AuditService` — SQLite `audit_log` append-only table with triggers blocking UPDATE/DELETE; every order/modify/cancel/fill/kill-switch logged.
- [ ] `KillSwitchService` — flatten-all endpoint that cancels all orders → closes all positions → disables all slots → broadcasts event.
- [ ] REST: `/slots`, `/orders`, `/positions`, `/balance`, `/universe`, `/audit`, `/killswitch`.
- [ ] WS: `/stream` pushing all live events.
- [ ] Mock `HyperliquidClient` for tests; `ShadowClient` wrapper deferred to Phase 11.

---

## Phase 3 — 🔴 UI Shell + Key Unlock (1 week)

**Goal:** Empty but usable Tauri app replacing Tkinter as the primary UI path.

**Tasks**

- [ ] Tauri 2 + Vite + React 19 + TypeScript project. Design tokens for dark + light themes.
- [ ] Layout: left sidebar (workspace switcher), main area, right inspector, titlebar with kill switch always visible.
- [ ] First-run wizard: import private key → stored to OS keychain via Tauri keyring plugin → wallet-address confirm.
- [ ] Connection layer: TanStack Query for REST, native WebSocket for `/stream`, auto-reconnect.
- [ ] Tauri sidecar config: spawn `uvicorn backend.main:app` on launch, terminate on exit.
- [ ] Installer packaging hook — produce `.exe` / `.dmg` / `.AppImage` (not shipped until Phase 12).

---

## Phase 4 — 🔴 Chart Workspace (3 weeks) 🎯 **Ship v0.1**

**Goal:** The TradingView-like chart, streaming live from Hyperliquid.

**Tasks**

- [ ] `lightweight-charts` v4+ integration. Price pane + indicator subpanes (volume, RSI, MACD, ATR).
- [ ] Symbol / interval picker with typeahead over full dynamic universe.
- [ ] Live streaming via WS: bar close → `update(bar)`.
- [ ] Crosshair with OHLCV + indicator readout at cursor.
- [ ] Drag zoom, scroll history, 1/2/4-chart grid layouts.
- [ ] Replay mode: play / pause / step / speed at 1× / 2× / 10× / 100×.

**Ship target:** installer with live BTC chart streaming + existing strategy running in a slot. No markup tools yet, no backtest yet.

---

## Phase 5 — 🔴 Markup + Chart-to-Order (2 weeks) 🎯 **Ship v0.2**

**Goal:** Annotate charts; dragging SL/TP on the chart modifies live orders on the exchange.

**Tasks**

- [ ] Drawing toolkit (see `OVERHAUL_PLAN.md` §7.3): trendline, horizontal/vertical/ray lines, rectangle, ellipse, fib retracement/extension/time zones, pitchfork, text, arrow, price range, date range, long position, short position.
- [ ] SVG markup layer over lightweight-charts, positioned via time↔px and price↔px converters.
- [ ] Snap-to-OHLC; lock/hide/group; z-order; copy/paste.
- [ ] Persistence: SQLite `layouts` + `markups` + `markup_templates` tables.
- [ ] Interactive long/short position tool with `draft → pending → active → closed` lifecycle.
- [ ] Drag SL/TP → debounced 200ms → modify exchange order. Confirmation modal above `confirm_modify_pct` threshold.
- [ ] Auto-fill markers: every filled order writes a `fill_marker` markup.
- [ ] Planned-trade overlay: draw a trade box → Arm button → POST to exchange.

**Ship target:** full markup + drag-to-trade on live orders.

---

## Phase 6 — 🔴 HIP-4 Outcome Workspace (2 weeks) 🎯 **Ship v0.3**

**Goal:** HIP-4 prediction markets as a first-class surface equal to the chart workspace.

**Tasks**

- [ ] Outcome Board: active markets grouped by category (crypto / politics / sports / macro), sortable by resolution date / implied prob / volume / model edge.
- [ ] Outcome Detail: probability curve (price bounded [0,1], not candlestick), resolution rule header, days-to-resolve countdown, order book panel, news feed filtered by event tags, `pricing_model.py` theoretical overlay, edge panel, trade panel.
- [ ] Outcome tape storage: `data/parquet/outcomes/market_id=<id>/...`.
- [ ] `OutcomeService.list_active() / get(id) / fetch_tape(id, from, to) / compute_edge(id)`.
- [ ] WS push: `/stream/outcomes?market_id=...`.
- [ ] `OutcomeSlot` parallel to `PerpSlot`. `TradeEngine` treats both uniformly via `SlotRunner` interface.
- [ ] Deploy `outcome_arb` as an outcome slot from the UI.

**Ship target:** HIP-4 workspace live, outcome_arb strategy deployable as a slot.

---

## Phase 7 — 🔴 Backtest Engine (2 weeks)

**Goal:** Replay history through the same strategy code that runs live.

**Tasks**

- [ ] `BacktestEngine.run(...)` event-driven simulator. Bar-by-bar; feeds DataFrame identical in shape to live into `strategy.analyze()`.
- [ ] `ExchangeShim` matching `HyperliquidClient` interface for simulated fills.
- [ ] Fills: market (next bar open), limit (touch), stop (touch), trailing. Slippage_bps + fee_bps + funding for perps.
- [ ] `BacktestResult` — equity curve, trades, metrics (total_return_pct, cagr, max_dd, sharpe, sortino, calmar, win_rate, profit_factor, expectancy, avg_win, avg_loss, max_consec_losses, trade_count, avg_hold_bars, pct_in_market).
- [ ] Walk-forward: rolling train/test windows, aggregate OOS.
- [ ] Parameter sweep: grid or random search, sortable results table.
- [ ] Monte Carlo: shuffle trade ordering, bound worst-case DD.
- [ ] Multi-slot portfolio backtest: N strategies in parallel against one clock, combined equity curve.
- [ ] UI: Backtest Lab tab with live-animated run + "Overlay trades on chart" action.

---

## Phase 8 — 🔴 Research Workbench (2 weeks)

**Goal:** Deep research built into the app, not a library of ad-hoc scripts.

**Tasks**

- [ ] Study registry `STUDIES`: correlation matrix, cointegration pairs, seasonality heatmaps, regime classifier, event study, funding-vs-price, volatility regime, outcome news impact.
- [ ] Each study: pure function → `StudyResult (DataFrame + charts + summary)`.
- [ ] UI: Research tab with dataset picker + study form + results view + "save to notebook."
- [ ] Notebook persistence: markdown + embedded charts, exportable to `.html` / `.pdf`.

---

## Phase 9 — 🔴 Analog / Pattern Search (2 weeks) 🎯 **Ship v0.4**

**Goal:** "Find past windows that look like now; show what happened next."

**Tasks**

- [ ] `AnalogEngine` service with two retrieval modes.
- [ ] DTW path: brute-force with LB_Keogh pruning over z-scored windows. Cache per (asset × interval × window_len).
- [ ] Embedding path: train small 1D-conv autoencoder → 64-dim bottleneck → FAISS IVF-PQ index.
- [ ] Index builder CLI: `python -m backend.tools.build_analog_index --symbol BTC --interval 1h --window-len 40`.
- [ ] REST: `POST /analog/query`, `POST /analog/index/rebuild`.
- [ ] UI: Analog Search tab with current window + top-N match grid + forward-return distribution plot. Filters: mode, scope, regime, date range.
- [ ] `AnalogDistributionFeature` — strict-no-leakage feature for ML pipeline.

**Ship target:** analog search live, usable for "what happened after similar setups" research.

---

## Phase 10 — 🔴 ML Training Pipeline (3 weeks)

**Goal:** Train models on historical data; trained models plug in as first-class strategies.

**Tasks**

- [ ] Feature store: versioned per asset + interval (`feature_set=core_v1`). Write to `data/parquet/features/...`. Incremental re-compute.
- [ ] `Feature` protocol; register core features (returns, EMAs, momentum, volatility, volume, microstructure, cross-asset).
- [ ] Labelers: `forward_return_n`, `triple_barrier(pt, sl, h)`, `direction_n`, `vol_adjusted_return`, `outcome_resolution_label`.
- [ ] Purged k-fold + embargo CV (Prado AFML ch. 7).
- [ ] Models: `xgb_cls`, `logreg`, `rf_cls`, optional `lstm`.
- [ ] Model registry: `data/models/<family>/<timestamp>/` with `model.pkl`, `features.json`, `label.json`, `metrics.json`, `config.json`.
- [ ] `MLStrategy(BaseStrategy)` — `get_strategy("ml:<model_id>")` returns a loaded model as a strategy.
- [ ] UI: Training Lab tab with config form → live run (progress via WS) → model card → "Promote to slot" action.

---

## Phase 11 — 🔴 Slots 2.0 + Mainnet Hardening Polish (1 week)

**Goal:** Power-user slot management + every safety layer live.

**Tasks**

- [ ] Per-slot config: ATR stops, trailing, MTF confirmation, regime filter, loss cooldown, volume confirm, RSI guard, ML model override.
- [ ] Per-slot mini-chart + live signal log.
- [ ] Aggregate exposure cap enforcement across all slots.
- [ ] Shadow-mode toggle per slot. `ShadowClient` wraps testnet `HyperliquidClient`; strategy runs twice per bar; divergence alerts.
- [ ] Confirmation modal thresholds configurable in Settings.
- [ ] Kill switch: keyboard shortcut + titlebar button + fat-finger guard (type "KILL" or hold 2s).

---

## Phase 12 — 🔴 Ship Polish (1 week) 🎯 **Ship v1.0**

**Goal:** Shippable.

**Tasks**

- [ ] Auto-update via Tauri updater.
- [ ] Installer packaging: `.exe` (NSIS) / `.dmg` / `.AppImage`.
- [ ] In-app log viewer with filtering.
- [ ] Optional crash reporting (Sentry).
- [ ] User guide: getting started, slot setup, backtest walkthrough, ML training walkthrough.
- [ ] Architecture guide: link to `Design.md` + `OVERHAUL_PLAN.md`.
- [ ] Keyboard shortcuts reference.
- [ ] Delete deprecated `gui/` and `dashboard.py`.

---

## Ship Targets

| Build | End of Phase | Feature Set |
|---|---|---|
| v0.1 | 4 | Installer + live chart + existing strategies running |
| v0.2 | 5 | + Markup tools + drag-to-modify live orders |
| v0.3 | 6 | + HIP-4 outcome workspace + outcome slots |
| v0.4 | 9 | + Backtest + research + analog search |
| v1.0 | 12 | + ML training + full hardening + auto-update |

## Wall-Clock Estimate

- **1 FTE:** 24 weeks serial.
- **2 FTE:** ~16 weeks (UI track + services track run in parallel after Phase 3).

---

## Non-Phased Backlog

Not blocking v1, but worth tracking:

- [ ] Replit / portable builds (non-Tauri) for research-only use cases.
- [ ] Reinforcement learning strategy class (PPO over backtest env) — deferred post-v1.
- [ ] TradingView Advanced Charts upgrade (replaces lightweight-charts, paid commercial license).
- [ ] Polygon.io equity data subscription for sub-minute US-equity history.
- [ ] LSTM / Transformer models — evaluate after XGBoost baselines are solid.
- [ ] Multi-user / cloud sync — only if ever needed. Single-user is the design target.
- [ ] Revit-plugin equivalent for equities / macro-dashboard embed — speculative.
