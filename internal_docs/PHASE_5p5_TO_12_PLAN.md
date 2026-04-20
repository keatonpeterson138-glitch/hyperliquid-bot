# Phase 5.5 → 12 Implementation Plan

Scope: everything from v0.2 polish through v1.0 ship. This doc reads alongside `OVERHAUL_PLAN.md` (which defines the *what*) and `path_to_v1.md` (phase tracker); this doc pins down the *how* — module boundaries, database strategy, historical-data bootstrap, per-phase exit criteria.

**Status baseline (as of 2026-04-20):**

| Phase | State | Notes |
|---|---|---|
| 0 | 🟡 mostly done | TradeEngine split partial; `dashboard.py` unwired |
| 1 | 🟢 done | 4 source adapters + router + Parquet lake + DuckDB catalog + CLI + updater + 4 REST endpoints |
| 2 | 🟢 done (today) | UniverseManager, KeyVault, AuditService, KillSwitch, SlotRepo, StreamHub, MarkupStore all wired in `backend/main.py` |
| 3 | 🟢 done | Tauri 2 + React 19 shell; sidebar + vault wizard + slots + audit + kill switch |
| 4 | 🟢 done | Chart workspace v0.1 w/ lightweight-charts v5, symbol/interval picker, source breakdown |
| 5 | 🟡 shell + polish | Markup CRUD + SVG overlay (horizontal / long / short / fill). 5.5 residual: drag-to-modify + `/orders` + armed lifecycle |
| 6 | 🟡 first slice | `/outcomes` listing + `/outcomes/{id}/edge` + Outcomes page + probability chart. Remaining: live WS, OutcomeSlot, `outcome_arb` deployable, order book panel |
| 7–12 | 🔴 | everything below |
| 13 | 🔴 | post-v1.0 desktop UX polish: top menu ribbon, Settings window, Wallet tab, Notes panel, command palette, Data Manager, export/print, notifications center, onboarding, light theme |

---

## 1. Database & storage architecture

Multi-store is already the baseline — this section pins down purpose, access pattern, and which phase writes what, so new code knows where to put things.

```
data/
├── app.db                 ← SQLite, transactional, always on
├── duckdb/
│   └── catalog.db         ← persistent DuckDB catalog + warm caches (Phase 7)
├── parquet/
│   ├── ohlcv/             ← Hive: symbol=/interval=/year=/part-000.parquet
│   ├── outcomes/          ← Hive: market_id=/year=/part-000.parquet
│   └── features/          ← Hive: symbol=/interval=/feature_set=/part-000.parquet (Phase 10)
├── analog/
│   ├── encoders/          ← autoencoder checkpoints (Phase 9)
│   └── indexes/           ← FAISS IVF-PQ (Phase 9)
├── models/                ← trained ML: <family>/<ts>/{model.pkl,features.json,label.json,metrics.json,config.json}
├── notebooks/             ← research notebook MDX + embedded charts (Phase 8)
└── backtests/             ← BacktestResult snapshots (Phase 7)
```

### 1.1 SQLite (`app.db`) — transactional state

Single source of truth for *state that changes*. All writes serialized by one in-process write lock. WAL mode; reads are cheap.

Tables in use today (migrations `001_initial.sql` + `002_markups.sql`):
- `schema_version` — applied migration versions.
- `markets`, `market_tags` — UniverseManager catalog.
- `audit_log` — append-only (UPDATE/DELETE blocked by triggers).
- `slots`, `slot_state` — slot config + runtime state (FK cascade).
- `layouts`, `markups` — chart drawings.

Add in later phases (migrations 003–006):
- `backtest_runs` (Phase 7) — `id, strategy, symbol, interval, from_ts, to_ts, config_json, metrics_json, created_at`.
- `study_runs` (Phase 8) — `id, study, inputs_json, result_path, created_at`.
- `analog_indexes` (Phase 9) — `id, symbol, interval, window_len, encoder_version, faiss_path, built_at`.
- `models` (Phase 10) — `id, family, version, path, features_json, label_json, metrics_json, promoted_slot_id, created_at`.
- `slot_configs_v2` (Phase 11) — per-slot advanced toggle column set; migrated from `slots`.

### 1.2 DuckDB + Parquet — columnar analytics

Today: DuckDB runs in-memory per-request, views built on top of the Parquet lake. Queries use partition pruning via `symbol=/interval=/year=` pushdown. That's fast enough for single-symbol reads but re-scans the lake on every process start.

Phase 7 change: switch to a **persistent DuckDB catalog at `data/duckdb/catalog.db`** that materializes views + maintains per-(symbol, interval) summary tables (min/max ts, bar count, last-ingested). One warm handle held by `DuckDBCatalog` for the backend's lifetime. Gives us:
- Sub-ms metadata lookups (no partition scan on first query).
- Warm plan cache (backtest replays hit the same plan many times).
- ~10–30× faster catalog listing on a fully-populated lake.

Backtest + feature-store queries stay in DuckDB (fast joins, window functions). Feature builds write Parquet — they don't mutate DuckDB.

### 1.3 FAISS + encoders — analog search (Phase 9)

One FAISS index per (symbol, interval, window_len, encoder_version). Encoder is a 1D-conv autoencoder (PyTorch) that produces a 64-dim bottleneck. Rebuilt incrementally as new data lands.

### 1.4 Model registry — flat files (Phase 10)

Each trained model is a directory under `data/models/<family>/<timestamp>/` holding `model.pkl` (joblib), `features.json`, `label.json`, `metrics.json`, `config.json`. `app.db.models` indexes this tree so the UI can list + promote without walking the FS.

### 1.5 Access patterns

| Store | Writes | Reads | Latency target |
|---|---|---|---|
| `app.db` | slot CRUD, audit append, markup CRUD | UI polls, trade-engine hot loop | <5ms |
| `duckdb/catalog.db` | periodic upsert on backfill | backtest, charts, analog | <50ms for range reads |
| Parquet | data_updater batches, feature builds | DuckDB only | (not direct) |
| FAISS | rebuild CLI | analog query endpoint | <100ms top-K |
| `data/models/` | train runs | load-on-demand for MLStrategy | <500ms model load |

---

## 2. Historical-data bootstrap ("hard-load everything")

Today the lake is empty (`data/parquet/` doesn't exist). Per the user request and §6.1 depth targets: load everything on first install, then incrementally keep it fresh.

### 2.1 Targets

| Timeframe | Depth | Per asset | Universe | Total |
|---|---|---|---|---|
| 1d  | 10+ yr | ~200 KB  | ~100 native + ~30 HIP-3 = 130 | ~26 MB |
| 1h  | 5–7 yr | ~5 MB    | 130 | ~650 MB |
| 15m | 3 yr   | ~10 MB   | ~50 (primary trade set) | ~500 MB |
| 5m  | 2 yr   | ~20 MB   | ~30 | ~600 MB |
| 1m  | 6–12 mo | ~50 MB  | ~15 (scalping-eligible) | ~750 MB |
| Outcomes | since creation | ~50 MB/mkt | ~100 curated | ~5 GB |
| **Total** | | | | **~7.5 GB** |

That fits on any modern SSD. The pain is wall time: free API tiers, rate limits, and API gaps across sources.

### 2.2 Bootstrap tool: `backend/tools/bootstrap_lake.py`

New CLI that wraps `backfill` + `UniverseManager.refresh()`:

```
python -m backend.tools.bootstrap_lake \
    --targets crypto,stocks,commodities,outcomes \
    --max-depth          # honor §6.1 targets end-to-end
    --parallelism 4      # workers × 4 = concurrent requests
    --resume             # checkpoint per (symbol, interval, year) slice
    --dry-run            # print plan, exit
```

Steps:
1. `UniverseManager.refresh()` — discover every live market.
2. For each (symbol, interval) in cross-product of universe × depth tier, call `SourceRouter.plan(from=depth_start)` → execute slices → append Parquet.
3. Checkpoint completed (symbol, interval, year) tuples in a `bootstrap_progress` SQLite table so `--resume` is cheap.
4. For outcomes: `OutcomeClient.list_markets()` + per-market tape pull since creation.
5. Warm the DuckDB catalog: run `ANALYZE` + materialize the summary views.

### 2.3 First-run UX (wired by Phase 11)

Tauri wizard step 1 (after vault unlock): **"Download historical data (~7 GB, ~30–90 min)"** — runs bootstrap in the backend with a progress stream (`/stream` events: `bootstrap.progress`, `bootstrap.done`). Operator can skip / run later / customize depth tiers.

Incremental keeper: `DataUpdater` (already in Phase 1) tails the latest bars every N minutes; catches the lake up on process start.

### 2.4 Validation

Bootstrap is done when:
- Per (symbol, interval) tier: `catalog.query_candles(symbol, interval, depth_start, now)` returns ≥ expected_bar_count × 0.95 (allow 5% gaps).
- `cross_validate` between Hyperliquid and a secondary source (Binance for BTC/ETH/SOL) shows close-price divergence < 0.5% over the last 30 days.
- `GET /catalog` returns a summary row per (symbol, interval) with earliest ≤ target depth.

---

## 3. Phase plans (5.5 → 12)

Each phase: goal → concrete subtasks (numbered for tracking) → exit criteria.

### Phase 5.5 — Chart-to-order (1 week)

**Goal.** Markups become live exchange orders. Drag SL/TP on the chart → debounced modify on the open order. Draw a position box → Arm → place bracket order.

Subtasks:
1. `POST /orders` REST endpoint backed by `OrderExecutor` (already in Phase 2.6). Body: `{symbol, side, size_usd, entry_type, entry_price?, sl_price, tp_price, leverage, slot_id?}`. Pre-flight validation (tick/size decimals, min size).
2. `PATCH /orders/{order_id}` — modify SL/TP on an open bracket. Debounced upstream by the UI (200ms).
3. `DELETE /orders/{order_id}` — cancel.
4. `POST /orders/from-markup` — promote a `long_position` / `short_position` markup (state `draft`) to `pending` → places order → markup tracks the `order_id`.
5. `MarkupLayer` drag handlers: pointer-down on a line, capture, snap-to-OHLC optional, emit `PATCH /markups/{id}` on drag-end + debounced `/orders/{id}` modify when `state='active'` with an `order_id`.
6. Confirmation modal: size > `confirm_above_usd` or modify Δ% > `confirm_modify_pct` triggers a modal with the pre/post view.
7. Fill-marker auto-write: `SlotRunner` / `OrderExecutor` fill callback → `MarkupStore.create(tool_id='fill_marker', payload={price, side}, state='closed')`.
8. Tests: unit (OrderExecutor mocks), API (`tests/unit/backend/api/test_orders.py`), UI (Playwright against Tauri dev — first e2e spec).

Exit: draw a long-position box on BTC testnet → Arm → order lands on exchange → drag SL → order modifies within 250ms → fill triggers fill_marker.

### Phase 6 (residual) — Outcome workspace (1 week)

**Goal.** HIP-4 markets are a first-class slot target. Probability curve streams live, pricing-model edge updates in real time, `outcome_arb` deployable as a slot.

Subtasks:
1. `OutcomeSlotRunner` — parallel to perp `SlotRunner`. Uses `OutcomeMonitor` for live ticks; runs `outcome_arb.analyze()` each tick (not per-bar). Respects the same `SlotRepository` contract.
2. `SlotRunner` interface unification: `SlotRunnerFactory.create(slot)` dispatches on `kind`. Drop the `if kind == ...` branching in `TradeEngineService`.
3. `/stream/outcomes?market_id=...` WS — channel-scoped subset of `/stream`; subscribers only see their market's ticks.
4. `OrderBookSnapshot` REST (`GET /outcomes/{id}/orderbook`) — L2 snapshot via `OutcomeClient`; polled at 500ms from the UI (no WS yet).
5. `UniverseManager.refresh()` needs a real `OutcomeClient` — wire in `backend/main.py` once the vault is unlocked (so API creds are available).
6. `PriceBinaryModel` DI — wire in `main.py` with the outcome client after vault unlock.
7. UI: order-book panel on Outcome Detail, trade panel (deploy slot + place direct order), news feed filtered by `market.bounds.event_tags`.
8. Tests: `OutcomeSlotRunner` integration, `/stream/outcomes` subscribe/unsubscribe, order-book REST.

Exit: `outcome_arb` runs as an outcome slot on testnet, trades when |edge| > threshold, WS pushes updates with <500ms lag, order book renders.

🎯 **Ship v0.3.** Tag `v0.3`, cut `.deb`/`.AppImage`/`.msi` via Phase 12 packaging once available — or hand-bundle for an internal dogfood.

### Phase 7 — Backtest engine (2 weeks)

**Goal.** Replay history through the same `strategy.analyze()` code that runs live. Produces an equity curve + metrics matching the live P&L surface.

Subtasks:
1. `BacktestEngine.run(strategy, symbol, interval, from_ts, to_ts, cash=, fees_bps=, slippage_bps=, funding=bool)` — event-driven bar-by-bar simulator.
2. `ExchangeShim` that matches `HyperliquidClient` interface: simulated fills for market (next-bar open), limit (touch), stop (touch), trailing. Funding accrual for perps.
3. `BacktestResult` dataclass: equity_curve DataFrame, trades DataFrame, metrics dict (total_return, CAGR, max_DD, sharpe, sortino, calmar, win_rate, profit_factor, expectancy, avg_win, avg_loss, max_consec_losses, trade_count, avg_hold_bars, pct_in_market).
4. Persist `BacktestResult` as `data/backtests/<run_id>.parquet` + `app.db.backtest_runs` row.
5. Walk-forward: `BacktestEngine.walk_forward(train_window, test_window, step)` → list[BacktestResult]. Aggregate OOS-only metrics.
6. Parameter sweep: `sweep(param_grid | random_n)` → ranked table. Parallelism via `concurrent.futures`.
7. Monte Carlo: shuffle trade ordering N times → 95% CI on DD + equity curve.
8. Multi-slot portfolio backtest: `BacktestEngine.portfolio([strategy_configs])` — one clock, correlated equity curve.
9. REST: `POST /backtest`, `GET /backtest/{id}`, `GET /backtest/{id}/equity.csv`.
10. UI: Backtest Lab page — config form → streaming progress → result card → "Overlay on chart" action.

Exit: `ema_crossover` backtested on BTC 1h over 2020–2026 matches a hand-spot-check on 3 trades; walk-forward + param sweep surface best params; DuckDB warm catalog keeps repeat runs under 5s.

### Phase 8 — Research workbench (2 weeks)

**Goal.** Studies — correlation, cointegration, seasonality, regime, event study — are first-class, not scripts.

Subtasks:
1. `Study` protocol: `run(inputs) -> StudyResult`. `StudyResult` = DataFrame + named charts + markdown summary.
2. Register core studies: `correlation_matrix`, `cointegration_pairs`, `seasonality_heatmap`, `regime_classifier`, `event_study`, `funding_vs_price`, `volatility_regime`, `outcome_news_impact`.
3. REST: `POST /research/run` (streams progress), `GET /research/{id}`. Results stored under `data/notebooks/`.
4. UI: Research page — dataset picker (symbol × interval × depth) + study form (dynamic from study schema) + result viewer.
5. Notebook persistence: append to a markdown file per project; embedded Vega-Lite or Plotly JSON spec; export to HTML/PDF via server-side render.

Exit: run `correlation_matrix` over the top 20 native perps 1h × 2 years → rendered heatmap + saved note → reopen a week later and result still loads.

### Phase 9 — Analog / pattern search (2 weeks)

**Goal.** "Find past windows that look like now; show what happened next."

Subtasks:
1. `AnalogEngine` service with **two** retrieval modes, selectable via `?mode=dtw|embedding`.
2. DTW path: LB_Keogh-pruned brute force over z-scored windows; cache per (symbol, interval, window_len).
3. Embedding path:
   - `AutoEncoder1D` (PyTorch) — 1D-conv + bottleneck 64-dim. Train with MSE on reconstructed normalized window.
   - `python -m backend.tools.train_encoder --symbol BTC --interval 1h --window-len 40` → saves `data/analog/encoders/ae_v1/*`.
   - `python -m backend.tools.build_analog_index --symbol BTC --interval 1h --window-len 40 --encoder ae_v1` → FAISS IVF-PQ under `data/analog/indexes/`.
4. REST: `POST /analog/query {symbol, interval, window, mode, top_k, scope=asset|universe, filters}`. `POST /analog/index/rebuild`.
5. UI: Analog Search page — current window plot + top-N grid of matches + forward-return distribution (median, 25/75, 5/95 bands) over N bars forward.
6. `AnalogDistributionFeature` (Phase 10 prep): strict-no-leakage feature that produces forward-return distribution stats for use as ML input.

Exit: query returns in <500ms for universe-scope on a 50-symbol index; forward-return distribution matches a hand-backtest of the "find and follow" heuristic within 2%.

🎯 **Ship v0.4.**

### Phase 10 — ML training pipeline (3 weeks)

**Goal.** Train models on historical data; trained models plug in as first-class strategies via `get_strategy("ml:<model_id>")`.

Subtasks:
1. Feature store:
   - `Feature` protocol: `compute(bars_df) -> pd.Series`. Deterministic, point-in-time safe (no forward peeks).
   - Register core features: `returns_{1,5,20}`, `ema_{12,26,50}`, `rsi_14`, `atr_14`, `volume_zscore`, `funding_rate_z`, `cross_asset_corr`, `analog_distribution_stats` (from Phase 9).
   - Version by `feature_set=core_v1`; write `data/parquet/features/symbol=/interval=/feature_set=/year=`.
   - Incremental builder: only compute new bars on subsequent runs.
2. Labelers: `forward_return_n`, `triple_barrier(pt, sl, horizon)` (Prado AFML ch. 3), `direction_n`, `vol_adjusted_return`, `outcome_resolution_label`.
3. Cross-validation: Purged k-fold with embargo (Prado ch. 7) — critical for non-IID financial data.
4. Model families: `xgb_cls` (primary), `logreg` (baseline), `rf_cls`. LSTM gated behind a feature flag, not v1.
5. Training run: `python -m backend.tools.train_model --family xgb_cls --feature-set core_v1 --label triple_barrier --symbol BTC --interval 1h`.
6. Model registry: writes `data/models/<family>/<ts>/` + inserts `app.db.models` row. Metrics stored both in `metrics.json` and the SQLite row for quick list queries.
7. `MLStrategy(BaseStrategy)` — loads a model by id, runs `analyze()` by assembling the feature vector at each bar. `get_strategy("ml:<model_id>")` returns it, deploying as a slot works unchanged.
8. REST: `POST /models/train` (streams progress), `GET /models`, `POST /models/{id}/promote` (flag as candidate for slot promotion).
9. UI: Training Lab — config form → live metric stream → model card (confusion matrix, feature importance, OOS equity) → "Promote to slot" button.
10. Purged CV + embargo unit tests to gate merges — easy to get wrong, catastrophic if silent.

Exit: `xgb_cls` trained on BTC 1h × 5 yr with `triple_barrier` labels; OOS sharpe > 0 on walk-forward; promoted to a shadow slot; runs in live loop without error for 24 hours.

### Phase 11 — Slots 2.0 + hardening (1 week)

**Goal.** Every power-user toggle exposed + every safety layer live.

Subtasks:
1. Migration 007: `slots` table → `slots_v2` with columns for ATR stops, trailing, MTF, regime filter, loss cooldown, volume confirm, RSI guard bounds, ML model override.
2. Per-slot config UI: form with grouped sections (risk / filters / advanced). Live preview of effective SL/TP in $ and % given size + leverage.
3. Per-slot mini-chart + live signal log (subscribes to the slot's `/stream` channel filter).
4. Aggregate exposure cap: `TradeEngineService.can_open_position(slot_id)` sums notional across slots; blocks if > cap. Cap editable in Settings.
5. Shadow-mode toggle per slot (`ShadowRunner` exists from P2.8, exposed via UI switch).
6. Confirmation modal thresholds: `confirm_above_usd`, `confirm_modify_pct`, `confirm_leverage_above` — editable in Settings, enforced by the UI before any POST.
7. Kill-switch polish: global keyboard shortcut (`Ctrl+Shift+K`) via `tauri-plugin-global-shortcut`; titlebar button always visible; fat-finger guard (type "KILL" *or* hold button 2s).
8. First-run data bootstrap integration (from §2.3) wired as a wizard step.

Exit: all toggles editable + persist, aggregate cap rejects an over-cap slot start with a clear error, kill-switch hotkey flattens all positions on testnet.

### Phase 12 — Ship polish (1 week)

**Goal.** Shippable.

Subtasks:
1. **Tauri sidecar bundling.** `src-tauri/src/lib.rs` spawns the Python backend as a child process on app start, kills it on window close. `tauri.conf.json::bundle.externalBin` ships a bundled Python + the `backend/` tree; start via `uvicorn backend.main:app --port 8787`. Options to evaluate: (a) bundled CPython (simplest, heaviest ~80MB install), (b) PyInstaller-frozen single-file (~50MB, occasional AV false-positives), (c) pyembed / pyoxidizer (cleanest, complex toolchain). Pick (a) for v1.0 unless installer size proves painful.
2. Auto-update via Tauri updater plugin + GitHub releases as the update feed.
3. Installer packaging matrix:
   - Windows: `.msi` (WiX) + `.exe` (NSIS) — **must build on Windows**.
   - macOS: `.dmg` + notarized bundle — **must build on macOS**.
   - Linux: `.AppImage` + `.deb` + `.rpm` — Linux CI.
   - Cross-build from WSL → Windows is possible via `cargo-xwin` but produces only the bare `.exe`, not an installer; use native builders.
4. In-app log viewer with filter by `source` (backend / UI / trade-engine / kill-switch) and severity.
5. Optional crash reporting: Sentry opt-in in Settings.
6. Docs: getting-started, slot setup, backtest walkthrough, ML training walkthrough, keyboard shortcuts, architecture guide (links `Design.md` + `OVERHAUL_PLAN.md`).
7. Delete `gui/` + `dashboard.py` + `bot.py` — deprecated surfaces fully replaced.

Exit: CI produces signed installers for all three OSes on tag push; `hyperliquid-bot.exe` double-click on a clean Windows VM installs, launches, opens wizard, completes vault + bootstrap, places a testnet trade. **Tag `v1.0`.**

🎯 **Ship v1.0.**

---

## 4. Cross-cutting concerns

### 4.1 Migrations

Add migrations atomically — never mutate an existing one. `schema_version` bumps per migration. Test the migration chain applies cleanly on an empty DB + on a DB at every prior version.

| # | Adds | Phase |
|---|---|---|
| 001 | markets, market_tags, audit_log, slots, slot_state | 2 |
| 002 | layouts, markups | 5 |
| 003 | backtest_runs, backtest_trades | 7 |
| 004 | study_runs | 8 |
| 005 | analog_indexes | 9 |
| 006 | models | 10 |
| 007 | slots_v2 (per-slot advanced config) | 11 |
| 008 | bootstrap_progress | 5.5 (with the bootstrap tool) |

### 4.2 DI wiring

`backend/main.py::_wire_services()` today wires 7 services with no network deps. Phases 6–11 extend it:
- Phase 6: wire `OutcomeClient` + `PriceBinaryModel` after vault unlock.
- Phase 7: wire `BacktestEngine` with the warm DuckDB catalog.
- Phase 9: wire `AnalogEngine` + encoder loader.
- Phase 10: wire `FeatureStore` + `ModelRegistry`.

Pattern stays: build in `_wire_services`, attach to `app.state`, override the API stub dependency.

### 4.3 Testing gates

Every phase ships with its own test layer. CI gates merges on: `pytest -q` green, `ruff check` green, new tests for new code, no coverage regression on strategies (`tests/unit/strategies/` golden-signal suite).

Add after:
- Phase 7: backtest determinism test — same inputs → same equity curve byte-for-byte.
- Phase 10: purged CV + embargo correctness tests.
- Phase 12: Playwright e2e on Tauri dev.

### 4.4 Performance budgets

Hot-loop targets on a modern laptop with the lake fully populated:
- `strategy.analyze()` tick-to-decision: < 5ms (excludes market-data fetch).
- `GET /candles` range of 1 year 1h data: < 80ms.
- `POST /backtest` for 2 yr × 1 strategy × 1 symbol: < 3s.
- `POST /analog/query` top-100: < 500ms universe-scope.
- Model inference per bar: < 2ms (XGBoost).

### 4.5 Sequencing (if parallel FTEs ever happen)

With one dev: 5.5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 (linear, ~13 weeks).

With two: split after Phase 6 into a **data/ML track** (7 → 8 → 9 → 10) and a **UI/safety track** (11 polish + chart-to-order refinement + Tauri sidecar + installer matrix prep). Re-sync at Phase 12 for ship polish. Saves ~5 weeks.

---

## 4.6 Phase 13 — Desktop UX polish (1 week, post-v1.0)

**Goal.** Fill the desktop-app ergonomics gaps that the phased roadmap didn't explicitly cover. These make v1.0 feel like a real Windows/macOS app instead of a web page in a frame.

Subtasks:

1. **Top menu bar (File / Edit / View / Window / Settings / Help).**
   - Native Tauri menu via `tauri::menu` (not HTML menu). Platform-appropriate (macOS top bar, Windows/Linux in-window).
   - File: New Layout, Open Layout, Save Layout, Save Chart as PNG, Export Candles CSV, Export Backtest CSV, Print Chart, Recent Files, Exit.
   - Edit: Undo/Redo markup changes, Cut/Copy/Paste markups, Select All, Find (Ctrl+F for symbol search).
   - View: Toggle sidebar, Toggle inspector, Light/Dark theme, Zoom, Fullscreen.
   - Window: List of open chart grids, Close tab, Reopen last closed.
   - Help: Shortcuts cheat-sheet (Ctrl+?), Docs, Changelog, About, Submit feedback.

2. **Settings window** (command: Ctrl+,). Tabbed:
   - **Exchange** — Hyperliquid testnet/mainnet toggle, API endpoint overrides, rate-limit config. Private keys route through the vault wizard — *never* plaintext in Settings.
   - **Wallets** — list linked wallets, primary wallet selector, add wallet (launches vault wizard), view address + explorer link.
   - **Notifications** — email SMTP, Telegram bot token + chat id, Slack webhook, desktop notifications on/off per event type.
   - **Risk defaults** — default SL/TP pct, `confirm_above_usd`, `confirm_modify_pct`, `confirm_leverage_above`, aggregate exposure cap.
   - **Data** — data root path, backfill throttle, cross-validate threshold, DuckDB cache size.
   - **Appearance** — dark/light, font size, compact/comfortable density, accent color.
   - **Advanced** — dev-mode toggle, log level, open data dir / log dir, reset workspace.
   - Persist to `data/settings.json` (file, not DB — survives DB migrations cleanly).

3. **Wallet tab in the left sidebar.**
   - Shows: primary wallet address (truncated w/ copy button), USDC balance, open positions, unrealised P&L, realised P&L (session / all-time), fee paid, transaction history (fills, deposits, withdrawals).
   - Actions: switch wallet, deposit/withdraw links (opens bridge or exchange page), copy address, view on explorer.
   - Data source: `GET /wallet/summary`, `GET /wallet/transactions`. New `WalletService` joins `orders` + `audit_log` + live exchange balance.

4. **Notes panel** (right inspector, per-workspace).
   - Free-form markdown notes with embedded chart screenshots.
   - "Insert chart screenshot" toolbar button grabs the current chart canvas to PNG, saves under `data/notes/<note_id>/img/<ts>.png`, inserts `![](...)` into the note.
   - Interactive blocks: insert backtest result, insert analog match grid, insert market quote — each rendered as a live widget in the note, not a static image.
   - Tags + search over notes. Persist to `app.db.notes` + `data/notes/` file store.
   - Per-note WS subscription so if a backtest cited in a note finishes, the note updates inline.

5. **Command palette** (Ctrl+K) — fuzzy search over: navigate to route, open symbol chart, run study, place order template, open settings pane, recent backtests. One global shortcut registered in Tauri.

6. **Data Manager tab** (sidebar).
   - Catalog browser — every (symbol, interval) in the lake with earliest/latest/bar count/source breakdown.
   - Trigger backfill from UI (no more CLI-only) — form calls `POST /backfill` with progress via `/stream`.
   - Cross-source divergence viewer.
   - Data-lake disk usage breakdown.

7. **Export infrastructure.**
   - `GET /export/candles.csv`, `GET /export/backtest/{id}.csv`, `GET /export/trades.csv`.
   - Print-chart: server-rendered SVG → PDF via `weasyprint` or headless Chromium. Exposed as `GET /export/chart.pdf?symbol=&interval=&from=&to=&layout_id=`.
   - "Save chart as PNG" uses Tauri's native save-file dialog + the browser's canvas `toBlob`.

8. **Recent activity / notifications center.**
   - Bell icon in the titlebar → dropdown of recent events (fills, kill-switch activations, backtest completions, data backfill completions, divergence alerts).
   - Subscribes to `/stream`; persists last 100 across sessions in `app.db.notifications`.

9. **Onboarding tutorial.**
   - First-run overlay after the vault wizard: 4-step guided tour (chart workspace → draw a long position → run a backtest → promote a model).
   - Dismissable; re-openable from Help menu.

10. **Theme + accessibility.**
    - Light theme (CSS variable palette already in place — just define the `:root[data-theme="light"]` overrides).
    - Keyboard-only navigation passes AXE-core checks on every page.
    - Reduced-motion respect for `prefers-reduced-motion`.

11. **Migrations + backend:**
    - Migration 009: `notes`, `notification_events`, `wallet_snapshots`.
    - New APIs: `/wallet/*`, `/notes/*`, `/export/*`, `/settings/*` (JSON-file-backed).

**Exit criteria.** All File/Edit/View/Settings/Help menu items functional (even if some open a "coming soon" dialog), Settings persists across restarts, Wallet tab shows a live balance, Notes panel embeds a screenshot + a backtest card, Command palette finds every route + every indexed symbol.

---

## 5. Open design decisions (to resolve per phase, not now)

- **Phase 7**: do we persist backtests in Parquet (portable) or directly in `app.db` blobs (simpler)? Current vote: Parquet, with the SQLite row holding the path + metrics.
- **Phase 9**: autoencoder on top of raw normalized OHLCV, or on `(return, vol, volume_z)` tuples? Latter is more robust but loses price structure.
- **Phase 10**: one feature set per asset (`core_v1_BTC`) or universal (`core_v1`)? Start universal; asset-specific is an easy follow-up.
- **Phase 12** sidecar: bundled Python vs PyInstaller — decide based on installer-size testing.

---

*Last updated: 2026-04-20.*
