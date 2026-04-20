# Hyperliquid Bot — Platform Overhaul Plan

**Status:** Aligned — scope locked, ready to execute.
**Date:** 2026-04-20
**User:** Single operator (owner's brother), mainnet trading.

---

## 1. Vision

Turn the current Tkinter trading bot (`dashboard.py`, 112KB monolith) into a **customizable TradingView-style trading + research workstation for Hyperliquid**, shipped as a single installer.

Core capabilities:

- **Live trading** on the full Hyperliquid universe — native perps, HIP-3 builder perps (stocks, commodities, FX, indices), and HIP-4 outcome/prediction markets.
- **TradingView-class charts** with a custom markup layer where drawings are live orders — drag SL/TP on the chart and the exchange modifies in real time.
- **Historical data platform** — maximum available depth per asset, stitched from multiple sources, stored locally in Parquet + DuckDB.
- **Analog / pattern search** — "find past windows that look like now" across the full history, both DTW and learned-embedding retrieval.
- **ML training pipeline** — purged k-fold + embargo CV, XGBoost baseline, trained models drop in as first-class strategies.
- **Backtest lab** — event-driven, walk-forward, Monte Carlo, multi-slot portfolio.
- **Outcome-market workspace** — equal-status surface alongside the chart for HIP-4 prediction markets.
- **Mainnet hardening from day one** — OS keychain, kill switch, exposure cap, confirmation modals, audit log, optional testnet shadow mode.

This is a replacement of `dashboard.py`, not a patch. Existing `core/exchange.py`, `core/market_data.py`, `core/risk_manager.py`, `core/outcome_*`, `core/pricing_model.py`, and `strategies/*` stay and are imported by the new service layer.

---

## 2. Current State (Baseline)

| Area | Status |
|---|---|
| Entry points | `bot.py` (CLI, single slot) + `dashboard.py` (Tkinter, 112KB monolith) |
| Exchange I/O | `core/exchange.py` — Hyperliquid SDK wrapper. Clean. **Keep.** |
| Market data | `core/market_data.py` — candle fetcher. **Keep, extend to multi-source stitching.** |
| Risk | `core/risk_manager.py` — SL/TP/daily-loss. **Keep, extend (ATR stops, cooldowns, aggregate cap).** |
| Strategies | `strategies/*.py` — 7 strategies + factory. **Keep; add `MLStrategy`.** |
| Outcome / HIP-4 | `core/outcome_*`, `core/pricing_model.py`, `strategies/outcome_arb.py`. Solid bones. **Keep + front-end surface.** |
| News | `core/news_monitor.py`, `core/email_notifier.py`, `core/telegram_notifier.py`. **Keep.** |
| GUI | `gui/*.py` + `dashboard.py`. **Replace.** |
| Persistence | `.env` only. **Add SQLite + Parquet lake.** |
| Historical data | None (fetched on-demand, not stored). **Build.** |
| Backtest | None. **Build.** |
| ML | None. **Build.** |
| Analog search | None. **Build.** |
| Safety (kill switch, audit) | None. **Build.** |

---

## 3. Target Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│  Desktop Shell (Tauri 2 + React 19 + TypeScript + Vite)                │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  UI Modules                                                      │  │
│  │   • Chart workspace (lightweight-charts + markup layer)          │  │
│  │   • Outcome workspace (HIP-4 prediction markets) 🆕              │  │
│  │   • Slot manager (perps + outcomes, N concurrent)                │  │
│  │   • Backtest lab                                                 │  │
│  │   • Research notebook                                            │  │
│  │   • Analog search (DTW + embedding) 🆕                           │  │
│  │   • ML training lab                                              │  │
│  │   • News + alerts                                                │  │
│  │   • Audit log viewer 🆕                                          │  │
│  │   • Settings + key vault                                         │  │
│  │   • Kill switch (always visible) 🆕                              │  │
│  └────────────────▲─────────────────────────────────────────────────┘  │
└───────────────────┼────────────────────────────────────────────────────┘
                    │  HTTP + WebSocket (localhost, token-auth)
                    │  JSON; msgpack for bulk candle frames
┌───────────────────┼────────────────────────────────────────────────────┐
│  Python Backend Service (FastAPI + uvicorn, Tauri sidecar)             │
│  ┌────────────────┴─────────────────────────────────────────────────┐  │
│  │  API routers                                                     │  │
│  │   /candles /orders /positions /markups /layouts /slots           │  │
│  │   /backtest /research /models /analog /news /outcomes            │  │
│  │   /audit /killswitch /stream(ws)                                 │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  Domain services                                                 │  │
│  │   UniverseManager · TradeEngine · BacktestEngine · ModelRegistry │  │
│  │   ResearchService · AnalogEngine 🆕 · OutcomeService 🆕          │  │
│  │   MarkupStore · LayoutStore · DataCatalog · AuditService 🆕      │  │
│  │   KillSwitchService 🆕 · ShadowModeRunner 🆕 · KeyVault 🆕       │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  Core (reused)                                                   │  │
│  │   core/exchange · core/market_data · core/risk_manager           │  │
│  │   core/outcome_* · core/pricing_model · core/news_monitor        │  │
│  │   strategies/* + MLStrategy 🆕                                   │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────┬───────────────────────────────────────┘
                                 │
┌────────────────────────────────┴───────────────────────────────────────┐
│  Storage                                                               │
│   data/parquet/ohlcv/    — OHLCV lake (symbol / interval / year)       │
│   data/parquet/features/ — computed feature tables                     │
│   data/parquet/outcomes/ — HIP-4 price/event tape 🆕                   │
│   data/analog/           — FAISS indices + encoders 🆕                 │
│   data/duckdb/catalog.db — query views over parquet/                   │
│   data/app.db            — sqlite: markups, layouts, slots, trades,    │
│                             backtests, models, universe, audit 🆕     │
│   data/models/           — trained model artefacts                     │
│   OS keychain            — private keys (never on disk unencrypted) 🆕 │
└────────────────────────────────────────────────────────────────────────┘
```

**Locked decisions:**

1. **Tauri 2 + React** — matches the StruxDraft stack, small binaries, Rust shell for native integrations (keyring, notifications, updater).
2. **FastAPI sidecar** — Python keeps doing strategies + ML + Hyperliquid SDK; the sidecar lifecycle is Tauri-managed so the user sees a single app.
3. **Parquet + DuckDB** for time-series, **SQLite** for relational app state. Zero ops, portable, fast enough.
4. **lightweight-charts** (Apache-2.0) as the chart engine; custom SVG markup layer on top — full ownership of interactions.
5. **Dynamic market universe** — `UniverseManager` discovers every market from Hyperliquid at startup. No hardcoded symbol list.
6. **Strategy contract unchanged** — `BaseStrategy.analyze(df, current_position) -> Signal`. ML models plug in as `MLStrategy(BaseStrategy)`. Backtest, shadow-mode, and live all share the same code path.
7. **Audit is append-only SQLite** — every order, fill, modify, kill-switch event written with full context. Exportable.

---

## 4. Phased Roadmap

12 phases. Ship a user-visible build at the end of every 🎯 phase.

### Phase 0 — Foundation (1 week)

- Split `dashboard.py` into `engine.py` + `state.py` + `view.py` so the live loop is extractable.
- Create `backend/` package (`api/`, `services/`, `models/`, `db/`, `main.py`).
- Create `ui/` Tauri + React + Vite + TS project.
- Add deps: `fastapi`, `uvicorn`, `duckdb`, `pyarrow`, `sqlalchemy`, `alembic`, `joblib`, `xgboost`, `scikit-learn`, `faiss-cpu`, `dtaidistance`, `cryptography`, `keyring`.
- Add CI workflow (lint, pytest, typecheck).
- Repo target layout:

```
hyperliquid-bot/
├── backend/              ← FastAPI service + domain services
├── ui/                   ← Tauri + React app
├── core/                 ← reused
├── strategies/           ← reused + MLStrategy added in Phase 10
├── scripts/
├── data/                 ← parquet + sqlite + models + analog indices
├── internal_docs/
└── bot.py                ← deprecated but works, uses TradeEngine
```

### Phase 1 — Data Platform (2 weeks)

- Source adapters: `HyperliquidSource`, `BinanceSource`, `CoinbaseSource`, `CryptoCompareSource`, `YFinanceSource` (+ optional `PolygonSource`).
- Parquet writer with Hive partitioning; DuckDB catalog views.
- Universal stitched backfill: for each asset, pull from whichever source(s) cover which date range. Dedupe by `(symbol, interval, timestamp, source)`.
- Incremental updater: tails each active market's latest candle into Parquet.
- `GET /candles` + `/catalog` endpoints.
- Backfill CLI: `python -m backend.tools.backfill --target all --depth max`.

See §6.

### Phase 2 — Backend, Trade Engine, Safety Scaffolding (2 weeks)

- `UniverseManager` — dynamic market discovery, tag subsets.
- `TradeEngine` — runs N slots in a thread pool; emits events on WS.
- `KeyVault` — OS keyring storage + unlock-on-start.
- `AuditService` — append-only SQLite table, every action logged.
- `KillSwitchService` — flatten-all endpoint + broadcast.
- REST: `/slots`, `/orders`, `/positions`, `/balance`, `/universe`, `/audit`, `/killswitch`.
- WS: `/stream` pushing `tick`, `candle_close`, `signal`, `order_filled`, `position_update`, `pnl_update`, `log`, `kill_switch_activated`, `shadow_divergence`.

See §13 for the hardening spec.

### Phase 3 — UI Shell + Key Unlock (1 week)

- Tauri shell, dark + light themes.
- Layout: left nav sidebar, main workspace, right inspector.
- First-run wizard: store private key to OS keychain.
- Connection layer: TanStack Query (REST) + native WS.
- Kill switch button visible at all times in titlebar.

### Phase 4 — Chart Workspace (3 weeks) 🎯 **Ship v0.1**

- lightweight-charts price pane + indicator subpanes (volume, RSI, MACD, ATR).
- Symbol / interval picker with typeahead across full universe.
- Live streaming via WS, bar close → chart update.
- Crosshair + OHLCV readout; drag zoom; 1/2/4-chart grid; replay mode (play/pause/step).

See §7.

### Phase 5 — Markup + Chart-to-Order (2 weeks) 🎯 **Ship v0.2**

- Drawing toolkit (see §7.3): trendline, fib, rectangle, ellipse, text, long/short position tool.
- Snap-to-OHLC, lock/hide/group, templates, per-chart layout persistence.
- Interactive long/short tools: draft → arm → pending → active → closed lifecycle. Drag SL/TP → modify live order.
- Planned trade overlays. Auto-fill markers.

See §7.3 + §9.

### Phase 6 — HIP-4 Outcome Workspace (2 weeks) 🎯 **Ship v0.3**

- Separate visualization surface for outcome contracts (probability curve, not candlestick).
- Outcome board: active markets grouped by category (crypto / politics / sports / macro), resolution dates, implied probabilities.
- Detail view per contract: probability history, order book, news feed, theoretical price from `pricing_model.py` overlaid.
- `OutcomeSlotManager` in the slot UI so `outcome_arb` and future outcome strategies run alongside perp strategies.
- Separate Parquet tape: `data/parquet/outcomes/<market_id>/part-000.parquet` with event-driven tick history.

See §8.

### Phase 7 — Backtest Engine (2 weeks)

- Event-driven simulator reusing `strategy.analyze()`.
- Fills: market / limit / stop / trailing with slippage + fees + perp funding.
- Metrics: equity, DD, Sharpe, Sortino, Calmar, profit factor, expectancy, consec losses, time-in-market.
- Walk-forward, parameter sweep, Monte Carlo, multi-slot portfolio mode.
- UI: Backtest Lab with live animated run + "overlay trades on chart."

See §10.

### Phase 8 — Research Workbench (2 weeks)

- Studies: correlation matrix, cointegration pair finder, regime classifier (HMM/rule), seasonality heatmaps, event studies (FOMC/CPI/earnings), funding-vs-price, volatility regime buckets, outcome-market news impact.
- UI: Research tab with dataset picker + study form + results view + "save to notebook" (markdown + embedded charts, exportable to `.html`/`.pdf`).

See §11.1.

### Phase 9 — Analog / Pattern Search (2 weeks) 🎯 **Ship v0.4**

- `AnalogEngine` service: DTW retrieval + learned-embedding retrieval via FAISS.
- Indexer: precompute windows, normalize, build FAISS index per (asset × interval × window-length × encoder).
- Query API: given `(symbol, interval, window_end, window_len)` → top-N matches with forward-return distributions.
- UI: Analog tab with current window + N-grid of matches + forward-outcome distribution plot.
- Feature generator: `AnalogDistributionFeature` so ML models can consume analog outcomes as features.

See §12.

### Phase 10 — ML Training Pipeline (3 weeks)

- Feature store in Parquet; per-asset feature tables.
- Labelers: forward-return-N, triple-barrier (pt/sl/h), direction-N, vol-adjusted-return.
- Purged k-fold + embargo CV.
- Models: XGBoost classifier baseline, logreg, random forest, optional LSTM.
- Model registry in `data/models/<family>/<timestamp>/`.
- `MLStrategy(BaseStrategy)` — loads model by id, emits signals.
- Training Lab UI: config form → run → model card → "promote to slot."

See §11.2.

### Phase 11 — Slots 2.0 + Hardening Polish (1 week)

- Per-slot advanced config: ATR stops, trailing, MTF confirmation, regime filter, loss cooldown, volume confirm, RSI guard, ML model override.
- Per-slot mini-chart + live signal log.
- Aggregate exposure cap enforcement.
- Shadow-mode toggle per slot; divergence alerts.
- Confirmation modal thresholds configurable.

See §13.6 for shadow-mode spec.

### Phase 12 — Ship Polish (1 week) 🎯 **Ship v1.0**

- Auto-update (Tauri updater).
- Installer packaging (`.exe` / `.dmg` / `.AppImage`).
- In-app log viewer.
- Crash reporting (optional, Sentry).
- User guide + architecture guide + keyboard shortcuts reference.

**Total: 24 weeks at 1 FTE.** User-visible ships at ends of Phase 4, 5, 6, 9, 12.

---

## 5. Asset Universe (Dynamic)

No hardcoded list. `UniverseManager` discovers markets from Hyperliquid at startup and tags them.

### 5.1 What's out there (as of April 2026)

| Class | Source | Examples |
|---|---|---|
| **Native perps** | `Info.meta()` | BTC, ETH, SOL, HYPE, + ~100 alts |
| **HIP-3 perps — stocks** | `Info.meta(dex='xyz')` | NVDA, TSLA, AAPL, MSFT, GOOGL, AMZN, META, HOOD, INTC, PLTR, COIN, NFLX, MSTR, AMD, TSM |
| **HIP-3 perps — indices** | `Info.meta(dex='xyz')` | SP500 (S&P-licensed, March 2026), XYZ100 (Nasdaq-100 synthetic) |
| **HIP-3 perps — commodities** | `Info.meta(dex='cash')` or similar | Gold, silver (COMEX), crude oil, corn, wheat |
| **HIP-3 perps — FX** | builder dexes | varies |
| **HIP-4 outcome contracts** | `Info.outcome_meta()` (SDK pending) | prediction markets (testnet; curated canonical first) |

### 5.2 Discovery + catalog

```python
class UniverseManager:
    def refresh(self) -> list[Market]:
        # Native perps
        native = self._fetch_perp_meta(dex="")
        # HIP-3 dexes — enumerate active deployers
        hip3 = []
        for dex in self._discover_active_dexes():        # ['cash', 'xyz', ...]
            hip3.extend(self._fetch_perp_meta(dex=dex))
        # HIP-4 outcomes
        outcomes = self._fetch_outcome_meta()
        all_markets = native + hip3 + outcomes
        self._upsert_markets(all_markets)
        return all_markets
```

SQLite schema:

```sql
CREATE TABLE markets (
    id              TEXT PRIMARY KEY,     -- canonical: 'perp:BTC', 'perp:xyz:TSLA', 'outcome:0x...'
    kind            TEXT NOT NULL,        -- 'perp' | 'outcome'
    symbol          TEXT NOT NULL,        -- 'BTC' | 'xyz:TSLA' | outcome market id
    dex             TEXT DEFAULT '',      -- '' | 'cash' | 'xyz' | ...
    base            TEXT,                 -- 'BTC' | 'TSLA' | base asset for outcome
    category        TEXT,                 -- 'crypto' | 'stock' | 'commodity' | 'fx' | 'index' | 'outcome'
    subcategory     TEXT,                 -- 'politics' | 'sports' | 'macro' | ... (outcomes)
    max_leverage   INTEGER,
    sz_decimals    INTEGER,
    tick_size      REAL,
    min_size       REAL,
    resolution_date TIMESTAMP,            -- outcomes only
    bounds_json    TEXT,                  -- outcomes only: {"min":0,"max":1}
    active         BOOLEAN DEFAULT 1,
    first_seen     TIMESTAMP,
    last_seen      TIMESTAMP
);

CREATE TABLE market_tags (
    market_id TEXT REFERENCES markets(id),
    tag       TEXT NOT NULL,              -- 'trade' | 'train' | 'watch' | user-defined
    PRIMARY KEY (market_id, tag)
);
```

UI: Universe panel shows every market, filter by category, toggle tags. New HIP-3 listings show up as "NEW" badge after next refresh (polled every 10 min).

---

## 6. Data Platform

### 6.1 Depth targets (training-driven)

Per Prado's *Advances in Financial Machine Learning* ch. 7, purged k-fold + embargo needs hundreds of samples per fold for stable metrics. These targets are the result:

| Timeframe | Target history | Size per asset (approx) | Purpose |
|---|---|---|---|
| 1d | 10+ years | ~3,650 bars / 200KB | Regime classifier, daily models, macro context |
| **1h** | **5–7 years** | **~50k bars / 5MB** | **Primary ML training + analog search** |
| 15m | 3 years | ~105k bars / 10MB | Intraday / day-trade models |
| 5m | 2 years | ~210k bars / 20MB | Short-horizon ML |
| 1m | rolling 6–12 months | ~260k–525k / 25–50MB | Scalping, microstructure (selected assets only) |

### 6.2 Source strategy per asset class

| Asset | Primary | Stitch-in | Target depth |
|---|---|---|---|
| BTC | Hyperliquid | Binance (2017+), Coinbase (2015+) | 2015 → now |
| ETH | Hyperliquid | Binance (2017+), Coinbase (2016+) | 2016 → now |
| SOL, HYPE, alts | Hyperliquid | Binance if listed pre-Hyperliquid | launch → now |
| Stocks (HIP-3) | Hyperliquid (since Oct 2025) | yfinance (underlying cash ticker, decades) | full cash history + HL tape |
| Indices (SP500, XYZ100) | Hyperliquid | yfinance (SPY/QQQ proxy 1993+, ES=F/NQ=F futures) | full underlying + HL tape |
| Commodities | Hyperliquid | yfinance (GC=F, SI=F, CL=F, ZC=F, ZW=F futures, decades) | full underlying + HL tape |
| Outcomes (HIP-4) | Hyperliquid tick tape | — | tape since market creation |

Dedupe key: `(symbol, interval, timestamp, source)`. `source` is preserved so we can weight recent-regime sources higher during training.

Source adapter contract:

```python
class DataSource(Protocol):
    name: str
    def supports(self, symbol: str, interval: str) -> bool: ...
    def fetch_candles(self, symbol, interval, start, end) -> pd.DataFrame: ...
    def earliest_available(self, symbol, interval) -> datetime | None: ...
```

`SourceRouter.plan(symbol, interval, start, end)` returns a sequence of (source, slice) tuples that together cover the range. Cross-validate mode: pull from two sources in parallel, alert if divergence > threshold.

### 6.3 Storage layout

```
data/
├── parquet/
│   ├── ohlcv/
│   │   └── symbol=BTC/interval=1h/year=2024/part-000.parquet
│   ├── outcomes/
│   │   └── market_id=0xabc/year=2026/part-000.parquet
│   └── features/
│       └── symbol=BTC/interval=1h/feature_set=core_v1/part-000.parquet
├── analog/
│   ├── index_embedding/
│   │   └── BTC_1h_40bar_ae_v1.faiss
│   └── encoders/
│       └── ae_v1/{model.pt, config.json, metrics.json}
├── duckdb/catalog.db     ← DuckDB views over parquet/
├── models/               ← trained ML artefacts
└── app.db                ← sqlite (app state)
```

Parquet schema (ohlcv): `timestamp, open, high, low, close, volume, trades, source, ingested_at`.

Parquet schema (outcomes): `timestamp, price, volume, implied_prob, best_bid, best_ask, event_id, source, ingested_at`.

### 6.4 API

```
GET  /candles?symbol=&interval=&from=&to=&source=
GET  /outcomes/{id}/tape?from=&to=
GET  /catalog
POST /backfill   {symbol, interval?, start?, end?, depth?: 'max'|'target'}  → {job_id}
WS   /stream/backfill/{job_id}          — progress events
WS   /stream/candles?symbol=&interval=  — live bar-close push
WS   /stream/outcomes?market_id=        — live tick push
```

---

## 7. Chart Workspace

### 7.1 Engine

**lightweight-charts v4+** (Apache-2.0). Canvas, fast, multi-pane. Drawings are our own SVG overlay — full control, no lib coupling. Upgrade path to TradingView Advanced Charts (paid) is clean — same markup schema, different renderer.

### 7.2 Composition

```
ChartContainer (React)
├── ChartToolbar           (symbol, interval, indicators, drawings, layouts)
├── ChartCanvas            (lightweight-charts)
│   ├── PricePane          (candles + volume)
│   ├── IndicatorPane[]    (RSI, MACD, ATR, custom, all removable)
│   └── MarkupLayer        (SVG overlay, positioned from time↔px, price↔px converters)
├── CrosshairReadout       (OHLCV + indicator values at cursor)
└── Statusbar              (connection, last tick, latency, replay state)
```

### 7.3 Markup toolkit

| Tool | Data | Notes |
|---|---|---|
| Trendline | `{p1, p2, extendL, extendR, style}` | |
| Horizontal line | `{price, label, style}` | |
| Vertical line | `{time, style}` | |
| Ray | `{p1, direction, style}` | |
| Rectangle | `{p1, p2, fill, style}` | |
| Ellipse | `{center, rx(t), ry(p), style}` | |
| Fib retracement | `{p1, p2, levels, style}` | |
| Fib extension | same + extension ratios | |
| Fib time zones | `{p1, p2, style}` | |
| Pitchfork | `{p1, p2, p3, style}` | |
| Text / callout | `{anchor, text, offset, style}` | |
| Arrow | `{p1, p2, style}` | |
| Price range (measure) | `{p1, p2}` | Δprice / Δ% / bars |
| Date range | `{t1, t2}` | Δtime / bars |
| **Long position** | `{entry, sl, tp, size, side:'long', state, order_ids}` | **Interactive, §9** |
| **Short position** | same, `side:'short'` | **Interactive, §9** |
| Fill marker | `{time, price, side, size, order_id}` | Auto from fills |

Each tool: `serialize`, `deserialize`, `render`, `hitTest`, `onDrag`, `cursorFor`, `validate`. Implemented as a plugin registry — new tools drop in without touching the shell.

### 7.4 Persistence

SQLite (`app.db`):

```sql
CREATE TABLE layouts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    symbol TEXT,
    interval TEXT,
    indicators_json TEXT,
    panes_json TEXT,
    created_at TIMESTAMP, updated_at TIMESTAMP
);

CREATE TABLE markups (
    id TEXT PRIMARY KEY,
    layout_id TEXT REFERENCES layouts(id),
    symbol TEXT, interval TEXT,
    tool_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    style_json TEXT,
    z INTEGER DEFAULT 0,
    locked BOOLEAN DEFAULT 0, hidden BOOLEAN DEFAULT 0,
    created_at TIMESTAMP, updated_at TIMESTAMP
);

CREATE TABLE markup_templates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    markups_json TEXT NOT NULL
);
```

Replay mode: toolbar toggle rewinds history and plays at 1×/2×/10×/100× with same UI state — drawing tools stay interactive.

---

## 8. Outcome Markets Workspace (HIP-4, v1)

Equal-status surface to the chart workspace. Not a tab-deep feature.

### 8.1 UI layout

```
OutcomeWorkspace
├── OutcomeBoard (left panel)
│   ├── category filter (crypto / politics / sports / macro / ...)
│   ├── active markets list
│   │   └── row: event title · implied prob · days to resolve · volume · tags
│   └── sort: resolution date | implied prob | volume | edge vs model
└── OutcomeDetail (main)
    ├── Header: event title, resolution rule, days/hours/mins to resolve, current implied prob
    ├── ProbabilityCurve (custom SVG, price bounded [0,1])
    │   ├── market-implied prob history
    │   ├── pricing_model.py theoretical prob overlay
    │   └── edge (implied – theoretical) as secondary panel
    ├── OrderBook panel
    ├── News feed (filtered by event tags, via core/news_monitor.py)
    ├── Trade panel (buy yes / sell yes / buy no / sell no, sized)
    └── Strategy panel (deploy outcome_arb as a slot here)
```

### 8.2 Data tape

```
data/parquet/outcomes/market_id=<id>/year=<yyyy>/part-000.parquet
  schema: timestamp, price, volume, implied_prob, best_bid, best_ask, event_id, source, ingested_at
```

### 8.3 Outcome-specific services

- `OutcomeService.list_active() / get(id) / fetch_tape(id, from, to)`
- `OutcomeService.compute_edge(id)` — compares market price to `pricing_model.py` fair.
- WebSocket push: `/stream/outcomes?market_id=...` for live tape.

### 8.4 Outcome slot

`OutcomeSlot` parallel to `PerpSlot`:
```python
@dataclass
class OutcomeSlot:
    id: str
    market_id: str
    strategy: str          # 'outcome_arb' | 'outcome_ml:<model_id>' | ...
    size_usd: float
    max_position_pct: float # of bankroll
    enabled: bool
    shadow_enabled: bool
    # strategy-specific params
```

`TradeEngine` treats both slot types uniformly via `SlotRunner` interface.

### 8.5 ML on outcomes

Outcome markets are too young for deep training on tape alone, but we can train **per-category** models (e.g., "crypto event + X days to resolve + Y implied prob → forward 1-day prob change") across all historical outcome markets, reusing `MLStrategy` with an outcome-specific feature set.

---

## 9. Chart-to-Order Integration

### 9.1 Drawing lifecycle

Long/Short position drawings have explicit states:

```
draft ──arm──▶ pending ──fill──▶ active ──close──▶ closed
                  │                  │
                  └── cancel ──▶ cancelled  ── archive
```

Visual:
- **draft** — dashed, yellow
- **pending** — dotted, amber, animated
- **active** — solid, green (long) / red (short); split filled / resting if partial
- **closed** — faded, with fill markers at entry + exit bars

### 9.2 Drag contract

Dragging any line on an armed drawing:
- **Entry** line (if not filled): `cancel_and_replace(order_id, new_price)`.
- **SL** line: `modify_stop(order_id, new_stop)`.
- **TP** line: `modify_order(order_id, new_price)`.

Drag is debounced 200ms after last movement before issuing. Confirmation toast on ACK; revert on reject.

For drags that change a price by > `confirm_modify_pct` (default 20%, configurable), a modal confirms before submit (see §13.4).

### 9.3 Arm → live

Draft position panel has: size USD, leverage, order type (market/limit), R:R validation. **Arm** → `POST /orders/from-markup` → server validates → submits → markup state → `pending`. If size USD > `confirm_above_usd`, modal confirms.

### 9.4 Fill markers

Every filled order writes an auto-markup with `tool_id='fill_marker'`. Read-only. Grouped under "Fills" layer; toggle to hide.

---

## 10. Backtest Engine

### 10.1 Simulator

```python
class BacktestEngine:
    def run(self, *, symbol, interval, strategy, params,
            start, end, size_usd, leverage,
            slippage_bps=2, fee_bps=3, funding=True,
            on_bar=None) -> BacktestResult: ...
```

Loop per bar `t`:
1. Check open orders vs bar H/L → fill at touch + slippage.
2. Update realised / unrealised P&L, funding accrual (perps).
3. `strategy.analyze(df_up_to_t, current_position)` → Signal.
4. Execute via `ExchangeShim` matching `HyperliquidClient` interface.
5. `on_bar` callback → UI live-animates.

### 10.2 Result

```python
class BacktestResult(BaseModel):
    equity_curve:  list[tuple[datetime, float]]
    trades:        list[Trade]
    metrics: dict  # total_return_pct, cagr, max_dd_pct, sharpe, sortino, calmar,
                   # win_rate, profit_factor, expectancy, avg_win, avg_loss,
                   # max_consec_losses, trade_count, avg_hold_bars, pct_in_market
    config: dict
```

### 10.3 Variants

- **Walk-forward** — rolling train/test windows, aggregate OOS.
- **Parameter sweep** — grid or random search, sortable results table.
- **Monte Carlo** — shuffle trade order, bounded worst-case DD.
- **Portfolio** — multiple strategies/symbols in parallel against one clock, combined equity curve.

### 10.4 UI integration

Post-run: "Overlay on chart" button adds entry/exit markers to the chart workspace; equity curve shown as a subpane.

---

## 11. Research + ML

### 11.1 Research studies

Each study is a pure function → `StudyResult (DataFrame + charts + summary)`:

```python
STUDIES = {
  "correlation_matrix":   CorrelationMatrix,    # full universe × interval
  "cointegration_pairs":  CointegrationPairs,   # Johansen or Engle-Granger
  "seasonality_heatmap":  SeasonalityHeatmap,   # hour-of-day, day-of-week, month
  "regime_classifier":    RegimeClassifier,     # HMM or rule-based
  "event_study":          EventStudy,           # FOMC, CPI, earnings, resolutions
  "funding_vs_price":     FundingVsPrice,       # perp funding correlates
  "volatility_regime":    VolatilityRegime,     # ATR buckets + outcomes
  "outcome_news_impact":  OutcomeNewsImpact,    # news → HIP-4 prob movement
}
```

UI: pick study → form → run → view → save to notebook (markdown + embedded plots; exportable `.html`/`.pdf`).

### 11.2 ML pipeline

**Feature store** — versioned feature sets, written per asset + interval:

```
data/parquet/features/symbol=BTC/interval=1h/feature_set=core_v1/part-000.parquet
```

`core_v1` ≈ returns (r_1/5/20, log), EMAs (9/21/50/200), ema ratios, momentum (RSI, MACD, MFI), volatility (ATR, BB pos, realised vol), volume (z-score, OBV), microstructure (range %, body %, gap %), cross-asset (BTC return, SPY return, VIX level, DXY change).

Feature contract:
```python
class Feature(Protocol):
    name: str; version: str; lookback: int
    def compute(df: pd.DataFrame, ctx: FeatureContext) -> pd.Series: ...
```

**Labelers:**
- `forward_return_n`
- `triple_barrier(pt, sl, h)` — Prado AFML ch. 3
- `direction_n`
- `vol_adjusted_return`
- `outcome_resolution_label` (HIP-4-specific)

**CV** — purged k-fold + embargo (AFML ch. 7). Embargo bars = horizon length to prevent train-test leakage.

**Models** — `xgb_cls` (baseline), `logreg`, `rf_cls`, `lstm` (optional). All via `joblib`; LSTM via torch-state-dict.

**Registry:**
```
data/models/<family>/<timestamp>/
  model.pkl | state_dict.pt
  features.json
  label.json
  metrics.json   # train/CV/OOS + confusion matrix + feature importance
  config.json
```

**Inference strategy:**
```python
class MLStrategy(BaseStrategy):
    def __init__(self, model_id, threshold_long=0.55, threshold_short=0.45): ...
    def analyze(self, df, current_position=None) -> Signal:
        x = self.model.featurize_latest(df)
        p_long = self.model.predict_proba(x)[-1, 1]
        ...
```

`get_strategy("ml:<model_id>")` in the factory. Same plumbing as rule-based strategies; backtest + shadow + live all work.

---

## 12. Analog / Pattern Search (v1 first-class)

Feature: "find past windows that look like now, and show what happened next."

### 12.1 Engine

Two retrieval modes, both enabled by default:

**DTW path (classic):**
- Walk history, extract windows of length L at stride S.
- Z-score each window (mean-zero, std-one) to make shape comparable across price regimes.
- Query: brute force DTW, pruned with LB_Keogh lower bounds.
- `O(N × L²)` — for 50k windows × 40 bars, ~a second on CPU. Cached per (asset × interval × L).

**Embedding path (learned):**
- Train a small 1D-conv autoencoder on all historical windows → 64-dim bottleneck.
- Index embeddings with FAISS IVF-PQ. Query: `O(log N)`, sub-10ms for 1M windows.
- Retrains on request or on data refresh.

Both modes return the same contract: `list[AnalogMatch]` where
```python
@dataclass
class AnalogMatch:
    symbol: str
    interval: str
    window_start: datetime
    window_end: datetime
    distance: float
    forward_returns: dict[int, float]    # {1: +0.3%, 5: +1.2%, 10: -0.4%, 20: +2.8%, 50: +5.1%}
```

### 12.2 Storage

```
data/analog/
├── index_embedding/
│   └── {asset}_{interval}_{window_len}_{encoder}.faiss
├── index_dtw_cache/
│   └── {asset}_{interval}_{window_len}.parquet   ← normalized windows, numpy-loadable
├── encoders/
│   └── {encoder_name}/{version}/{model.pt, config.json, training_metrics.json}
└── meta/
    └── {asset}_{interval}_{window_len}.parquet   ← timestamps parallel to faiss index
```

### 12.3 API

```
POST /analog/query
  body: {
    symbol, interval, window_end, window_len,
    mode: 'dtw' | 'embedding' | 'both',
    top_n: 20,
    scope: 'same-asset' | 'cross-asset' | 'category:<cat>',
    regime_filter?: 'trending' | 'ranging' | 'vol_expansion'
  }
  → { matches: AnalogMatch[], aggregated_outcomes: OutcomeDistribution }

POST /analog/index/rebuild   {symbol, interval, window_len, encoder?}   → job_id
```

`OutcomeDistribution`:
```python
@dataclass
class OutcomeDistribution:
    horizon_bars: int
    median_return: float
    iqr: tuple[float, float]
    hit_rate: float
    sharpe: float
    sample_count: int
    histogram: list[tuple[float, int]]
```

### 12.4 UI

**Analog Search tab**:
- Current window chart (left, 60% width).
- Top-N match grid (right, 40% width): each cell = mini chart of match with forward bars highlighted + outcome summary beneath.
- Filters: top-N, mode, scope, regime filter, date range.
- Clicking a match opens it full-size in the chart workspace with a "jump back" button.
- Forward-return distribution plot: histogram + density; horizon switcher (1 / 5 / 10 / 20 / 50).
- Save query → `saved_analog_sets` table.

### 12.5 ML integration

Feature: `AnalogDistributionFeature(window_len=40, horizon=10, top_n=20, mode='embedding')`. At each row, runs an analog query (using only data up to `t` — strict no-leakage), aggregates outcomes, returns `{median, iqr_width, hit_rate, sharpe, sample_count}` as features. Adds strong prior signal for models.

---

## 13. Mainnet Hardening

Non-negotiable from day one. Every item runs under `AuditService` — all security-relevant events are logged.

### 13.1 Key vault

- Private keys stored in **OS keychain** via Tauri keyring plugin:
  - Windows: Credential Manager
  - macOS: Keychain
  - Linux: libsecret (GNOME Keyring / KWallet)
- Backend receives key via one-time unlock at app start; held in-memory only.
- `.env` fallback **only if** `DEV_MODE=1` env var is set (logs a big warning).
- First-run wizard: import private key → confirm wallet address → store → wipe from UI state.

### 13.2 Kill switch

- Global keyboard shortcut: `Ctrl+Shift+Q` (configurable).
- Always-visible red button in titlebar.
- Action sequence (atomic, with audit entry per step):
  1. Cancel all open orders (`exchange.cancel_all()`).
  2. Market-close every open position.
  3. Disable every slot (`enabled=false` in DB).
  4. Broadcast `kill_switch_activated` WS event.
  5. UI enters "killed" mode — all trade surfaces disabled until explicit re-enable.
- Fat-finger guard: modal requires typing "KILL" or holding button 2 seconds.

### 13.3 Aggregate exposure cap

`MAX_AGGREGATE_EXPOSURE_USD` — user-configurable, default $25k.
Enforced by `RiskManager.pre_order_check()`: `sum(|pos_notional|) + sum(|pending_notional|) + new_order_notional ≤ cap`. On breach: reject order, audit, toast.

### 13.4 Confirmation modals

Two thresholds, configurable in Settings:
- `confirm_above_usd` (default $1,000) — any new order above this size → modal with full trade summary.
- `confirm_modify_pct` (default 20%) — drag-to-modify that changes price by > this → confirm.

### 13.5 Audit log

```sql
CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    event_type TEXT,     -- 'order_placed' | 'order_modified' | 'order_cancelled'
                         -- 'position_opened' | 'position_closed' | 'kill_switch'
                         -- 'slot_started' | 'slot_stopped' | 'risk_breach'
                         -- 'shadow_divergence' | 'key_unlock' | 'config_change'
    slot_id TEXT, strategy TEXT, symbol TEXT,
    side TEXT, size_usd REAL, price REAL,
    reason TEXT,
    exchange_response_json TEXT,
    source TEXT          -- 'user' | 'strategy' | 'risk_manager' | 'kill_switch'
);
CREATE INDEX idx_audit_ts     ON audit_log(ts);
CREATE INDEX idx_audit_symbol ON audit_log(symbol);
```

- Append-only (schema triggers block UPDATE/DELETE).
- UI: Audit tab with filters (event type, symbol, slot, date range) and CSV export.
- Every WS event that goes to the UI is also written here — single source of truth for "what happened."

### 13.6 Shadow mode

- Per-slot toggle: `shadow_enabled: bool`.
- When on, `TradeEngine` runs the strategy twice per bar: once against `HyperliquidClient(testnet=False)`, once against `ShadowClient(testnet=True)`.
- Shadow P&L tracked in `shadow_trades` table. UI surfaces "Testnet divergence" panel per slot.
- Alert when `|mainnet_pnl - shadow_pnl| > threshold` (default 5% over 1 day).
- Use case: testing strategy updates in parallel with a live slot without risking capital.

---

## 14. Data Flows (end-to-end reference)

### 14.1 Live trading, bar close

```
Hyperliquid WS (candle close)
  → DataUpdater.append(bar)                         ─▶ parquet/ohlcv
  → emit 'candle_close', symbol, bar
  → TradeEngine.on_bar_close(bar):
       for slot in active_slots.filter(symbol):
         df = DataCatalog.query(symbol, interval, tail=N)
         if RiskManager.pre_check(slot):
           signal = slot.strategy.analyze(df, slot.current_position)
           if signal.type != HOLD:
             if RiskManager.exposure_ok(slot, signal):
               order = exchange.place(...)        ─▶ AuditService.log('order_placed')
               broadcast('order_placed', order)
               if slot.shadow_enabled:
                 shadow_order = shadow_client.place(...)   # testnet
                 broadcast('shadow_order', shadow_order)
  → WS /stream push to UI
  → UI chart calls lightweight-charts.update(bar)
  → UI slot panel re-renders signal + P&L
```

### 14.2 User drags SL on chart

```
ui: MarkupLayer.onDragEnd(markup, handle, newPrice)
  → debounce 200ms
  → if |Δprice/price| > confirm_modify_pct: show confirmation modal
  → PATCH /markups/{id} { payload.sl: newPrice }
  → MarkupStore.update(id, payload)
  → if markup.state == 'active': OrderManager.modify_sl(order_id, newPrice)
  → exchange.modify_order(...)       ─▶ AuditService.log('order_modified')
  → WS push 'order_modified'
  → UI refresh; on reject → revert to previous price
```

### 14.3 Analog query

```
ui: Analog tab submits {symbol, interval, window_end, window_len, mode, top_n, scope}
  → POST /analog/query
  → AnalogEngine.query(...)
      mode=dtw:       brute-force DTW with LB_Keogh pruning over cached normalized windows
      mode=embedding: encoder.embed(query) → FAISS.search → top-N indices
      mode=both:      run both, merge by rank with user-chosen weights
  → for each match, compute forward_returns at {1,5,10,20,50} bars
  → return matches + OutcomeDistribution
  → UI renders grid + histogram + density plot
```

### 14.4 Backtest + shadow

```
ui: BacktestLab submits config
  → POST /backtest   → job_id
  → WS /stream/backtest/{job_id}
        'progress' pct, 'bar' (t, equity, position), 'trade', 'complete' (result)
  → UI live-animates equity curve
  → complete → save to app.db → results pane
  → "Overlay on chart" button writes trade markers as markups to the chart layout
```

### 14.5 HIP-4 outcome market cycle

```
UniverseManager.refresh() picks up new outcome market
  → OutcomeService.subscribe(market_id)  (Hyperliquid WS)
  → on tick: write to parquet/outcomes/{id}/... + WS push
  → UI OutcomeDetail renders probability curve live
  → pricing_model.py computes theoretical → edge panel
  → user deploys outcome_arb slot on this market
  → slot is a first-class SlotRunner, audited & killable same as perp slots
  → at resolution: event settles, slot auto-closes, audit log captures settlement P&L
```

### 14.6 ML training

```
ui: Training Lab submits TrainingConfig (symbol, interval, feature_set, label, model, cv, dates)
  → POST /models/train  → job_id
  → Trainer runs in ProcessPoolExecutor
  → WS progress events (fold N/K, metric snapshot)
  → on complete: model card written to data/models/<family>/<ts>/
  → model surfaces in Slot Manager as strategy='ml:<family>/<ts>'
  → user promotes: attach to a slot (optionally in shadow-mode first)
```

---

## 15. Open Decisions (now short list)

1. **TradingView Advanced Charts upgrade** — ship on lightweight-charts (Apache-2.0) for v1. Revisit after Phase 5 based on whether users need TV's premium drawings.
2. **Polygon.io subscription for equities** — defer. yfinance is enough for historical training; Polygon only matters if we need minute-latency equity data for live trades (HIP-3 equity perps give us the actual trade tape anyway).
3. **LSTM/Transformer in v1** — not. XGBoost + random forest + logreg only. Revisit after first ML ship.
4. **Sentry crash reporting** — nice-to-have, defer to Phase 12.

---

## 16. Migration Plan (don't break `bot.py`)

- Phase 0 extracts `TradeEngine` from `dashboard.py`; `bot.py` switches to use it. CLI still works.
- `core/*` and `strategies/*` untouched throughout — all new code imports from them.
- Old `gui/*` + `dashboard.py` remain runnable until Phase 3 UI ships → marked deprecated after v0.1 ship → deleted in Phase 12.

---

## 17. Success Criteria (end of Phase 12 = v1.0)

1. Single installer (`.exe` / `.dmg` / `.AppImage`). No Python env needed.
2. First launch: import private key → stored to OS keychain. Never written to disk unencrypted.
3. Hyperliquid universe discovered dynamically at startup; brother can tag subsets (trade / train / watch). New HIP-3 listings auto-appear.
4. Live chart of any discovered market, 1h bars back 5+ years, pans/zooms at 60 fps.
5. Draw a short-position tool on the chart → arm → order live on Hyperliquid mainnet → drag SL → order modifies on exchange within 300ms of mouse-up.
6. Kill switch flattens all positions and cancels all orders in < 2 seconds.
7. Backtest any strategy on any discovered market back to source earliest, 1h bars, results in under 30 s.
8. Train an XGBoost classifier on 5 years of BTC 1h bars with purged 5-fold CV; deploy model as a shadow-mode slot on testnet.
9. Analog search: query "last 40 bars of BTC 1h" → 20 matches across history in < 2 s with forward-return distributions.
10. HIP-4 outcome workspace: see active outcome markets, probability history, theoretical-vs-market edge, deploy `outcome_arb` as a slot.
11. Save a chart layout with 10 markups and 3 indicators → reopen next session → restored exactly.
12. Audit log captures every order, modify, fill, kill-switch event → exportable as CSV.
13. Shadow mode on a slot shows divergence between mainnet and testnet runs; alert fires if divergence exceeds threshold.

---

## 18. Effort Estimate

| Phase | Focus | Weeks |
|---|---|---|
| 0 | Foundation | 1 |
| 1 | Data platform | 2 |
| 2 | Backend + engine + hardening scaffolding | 2 |
| 3 | UI shell + key unlock | 1 |
| 4 | Chart workspace 🎯 v0.1 | 3 |
| 5 | Markup + chart-to-order 🎯 v0.2 | 2 |
| 6 | HIP-4 outcome workspace 🎯 v0.3 | 2 |
| 7 | Backtest engine | 2 |
| 8 | Research workbench | 2 |
| 9 | Analog / pattern search 🎯 v0.4 | 2 |
| 10 | ML training pipeline | 3 |
| 11 | Slots 2.0 + hardening polish | 1 |
| 12 | Ship polish 🎯 v1.0 | 1 |
| **Total** | | **24 weeks** @ 1 FTE |

Parallelisable with 2 FTE: Phases 4+5 (UI track) can run alongside Phases 6–9 (services track) once Phase 3 is done, collapsing wall-clock to ~16 weeks.
