# Hyperliquid Bot — Design Document

## 1. Document Purpose

This document is the technical reference for the Hyperliquid Trading Bot. It lets a contributor (human or AI) understand the product vision, trading basis, engineering boundaries, and subsystem architecture without having to re-read the full codebase.

Companion docs:
- `OVERHAUL_PLAN.md` — v1.0 architecture + 12-phase rollout plan. Read first for any overhaul work.
- `Changelog.txt` — append-only record of changes.
- `../todo/path_to_v1.md` — phase-by-phase status tracker.
- `../CLAUDE.md` — quick reference for AI assistants.

## 2. Product Vision

A **customizable desktop trading + research workstation for Hyperliquid** — single installer, mainnet-grade, covering the entire Hyperliquid market universe (native perps, HIP-3 builder perps, HIP-4 outcome contracts).

Primary value proposition:

- Live automated trading across crypto perps, tokenized equities, commodities, indices, FX, and prediction markets through one interface.
- TradingView-style interactive charts where **drawings are live orders** — drag an SL line on a chart and the exchange modifies the stop in real time.
- Local historical data platform (Parquet + DuckDB) with maximum available depth per asset, stitched from multiple sources.
- Backtest, walk-forward, Monte Carlo, and portfolio simulations using the same strategy code that runs live.
- ML training pipeline with time-series-correct cross-validation; trained models plug in as first-class strategies.
- **Analog / pattern search** — "find past windows that look like now, and show what happened next."
- HIP-4 prediction-market workspace as an equal-status surface to the chart workspace.
- Mainnet hardening from day one: OS keychain, kill switch, exposure cap, confirmation modals, append-only audit log, optional testnet shadow mode.

It is not intended to be a general-purpose exchange aggregator. It is Hyperliquid-first.

## 3. Users and Required Expertise

Primary user (as of April 2026):

- Single operator, mainnet trading. Crypto-fluent, familiar with perps mechanics and HIP-4 outcome contracts.

Required expertise:

- Understanding of perpetual futures, leverage, funding rates, SL/TP mechanics.
- Familiarity with Hyperliquid's market structure (native perps, HIP-3 dexes, HIP-4 outcomes).
- Comfort with reading strategy logic and tuning risk parameters.

Not required:

- Python coding — users can drive everything via the dashboard (current) or Tauri UI (v1).
- ML background — the training pipeline will use sensible defaults.

## 4. Trading Basis

- **Exchange:** Hyperliquid (mainnet + testnet).
- **Market classes:**
  - Native perpetual futures (crypto).
  - HIP-3 builder-deployed perps (stocks, indices, commodities, FX).
  - HIP-4 outcome contracts (binary / bounded prediction markets).
- **Order types supported:** market, limit, stop, trailing stop.
- **Leverage:** per-market, up to 50×. Isolated margin for HIP-3; cross default for native.
- **Funding:** tracked per-perp; included in backtest P&L.
- **Settlement:** HIP-4 outcomes settle 0 or 1 (binary) or within a defined range (bounded).

## 5. Current Architecture (as-shipped)

### 5.1 Entry points

- **`bot.py`** (~250 LOC) — headless CLI. Single slot, single strategy. Initializes `HyperliquidClient` + `MarketData` + `RiskManager` + strategy → loops every `LOOP_INTERVAL_SEC`.
- **`dashboard.py`** (2,431 LOC, Tkinter) — desktop GUI. Assembles tabs from `gui/`, runs the trading engine on a background thread, surfaces live P&L, news, predictions, logs, settings. This is the primary UI today and the subject of the overhaul.

### 5.2 Core modules (`core/`)

No strategy logic lives here. These modules are exchange/infra-facing and will be reused in the v1 overhaul.

- **`exchange.py`** — `HyperliquidClient` wraps the Hyperliquid SDK (`Exchange`, `Info`). Handles account init from private key, market price lookup, candle fetch, position queries, order placement/modification/cancellation, leverage setting. Supports `dex=` for HIP-3 markets.
- **`market_data.py`** — `MarketData.fetch_candles(symbol, interval, limit)` returns OHLCV DataFrames.
- **`risk_manager.py`** — `RiskManager` tracks daily P&L against cap, max open positions, SL/TP thresholds. `can_trade()`, `can_open_position()`, `check_position_exit()` gates.
- **`news_monitor.py`** — RSS / API poller with keyword filters. Feeds the dashboard news tab.
- **`email_notifier.py`, `telegram_notifier.py`** — Alert delivery via SMTP and Telegram Bot API.
- **`outcome_client.py`** — HIP-4 outcome contract client. Lists markets, fetches tape, places outcome orders.
- **`outcome_monitor.py`** — Polls outcome markets, emits events on probability changes.
- **`pricing_model.py`** — Theoretical outcome pricing (Bayesian base-rate models). Produces fair-value vs market-implied probabilities for edge detection.

### 5.3 Strategies (`strategies/`)

All strategies subclass `BaseStrategy` and implement:

```python
def analyze(self, df: pd.DataFrame, current_position: Optional[str] = None) -> Signal
```

Implemented strategies:

| Strategy | File | Type | Notes |
|---|---|---|---|
| EMA crossover | `ema_crossover.py` | Trend | 9/21 fast/slow defaults |
| RSI mean reversion | `rsi_mean_reversion.py` | Mean reversion | RSI 14, 30/70 thresholds |
| Breakout | `breakout.py` | Momentum | 20-bar lookback, 0.5% threshold |
| Funding dip | `funding_dip.py` | Perp-specific | Funding-rate fade |
| Outcome arbitrage | `outcome_arb.py` | HIP-4 | 665 LOC; uses `pricing_model.py` for edge |

`factory.py` registers all strategies. `get_strategy(name, **params)` is the extension point.

### 5.4 GUI (`gui/`)

Tkinter tabs, ~3,000 LOC. **Replaced in overhaul.**

| Tab | File | LOC |
|---|---|---|
| Dashboard | `dashboard_tab.py` | 138 |
| Predictions (HIP-4) | `predictions_tab.py` | 638 |
| News | `news_tab.py` | 248 |
| Settings | `settings_tab.py` | 578 |
| Logs | `log_tab.py` | 75 |
| Help | `help_tab.py` | 743 |

Shared: `sidebar.py`, `components.py`, `chart_widget.py`, `theme.py`.

### 5.5 Configuration (`config.py`)

`.env`-driven via `python-dotenv`. Notable surfaces:

- Credential + market selection surfaces (see `CLAUDE.md` §Configuration).
- `TIMEFRAME_DEFAULTS` — per-interval SL/TP/leverage recommendations.
- `MAX_SLOTS = 5` — multi-slot parser at `Config._parse_slots()`.
- `apply_timeframe_defaults(interval)` — one-shot preset application.
- `validate()` — credential + market format check; raises with actionable errors.

## 6. Target Architecture (v1.0)

See `OVERHAUL_PLAN.md` for the full spec. High-level layers:

```
Tauri desktop shell (React 19 + TS + Vite)
  ↔ HTTP + WebSocket
FastAPI Python sidecar
  → domain services (UniverseManager, TradeEngine, BacktestEngine,
    ResearchService, AnalogEngine, OutcomeService, ModelRegistry,
    MarkupStore, LayoutStore, AuditService, KillSwitchService, KeyVault)
  → core/ + strategies/ (reused)
  → Parquet + DuckDB (market data, features, outcomes, analog indices)
  → SQLite (app state: markups, layouts, slots, audit, models, universe)
  → OS keychain (private keys)
```

Highlights:

- Charts: `lightweight-charts` (Apache-2.0) + custom SVG markup layer. Interactive long/short drawings are live orders.
- Data: Parquet lake partitioned by symbol/interval/year; DuckDB views; SQLite for relational app state.
- Safety: OS keychain for keys, always-visible kill switch, aggregate exposure cap, confirmation modals, append-only audit log.

## 7. Data Layer (v1.0)

### 7.1 Storage

```
data/parquet/ohlcv/     symbol=<s>/interval=<i>/year=<y>/part-000.parquet
data/parquet/outcomes/  market_id=<id>/year=<y>/part-000.parquet
data/parquet/features/  symbol=<s>/interval=<i>/feature_set=<v>/part-000.parquet
data/analog/            faiss indices + autoencoder checkpoints
data/duckdb/catalog.db  views over parquet/
data/app.db             sqlite: universe, markups, layouts, slots, audit, models
data/models/            trained ML artefacts
```

### 7.2 Source strategy

Per asset, stitched multi-source to maximize history:

| Asset class | Primary | Stitch-in | Target depth |
|---|---|---|---|
| BTC / ETH | Hyperliquid | Binance (2017+), Coinbase (2015+) | 2015 → now |
| SOL, HYPE, alts | Hyperliquid | Binance if pre-Hyperliquid | launch → now |
| Stocks (HIP-3) | Hyperliquid (Oct 2025+) | yfinance (underlying ticker, decades) | full cash + HL tape |
| Indices | Hyperliquid | yfinance (SPY, QQQ, ES=F, NQ=F) | full underlying + HL tape |
| Commodities | Hyperliquid | yfinance (GC=F, SI=F, CL=F, ZC=F, ZW=F) | full underlying + HL tape |
| HIP-4 outcomes | Hyperliquid tape | — | since market creation |

Dedupe key: `(symbol, interval, timestamp, source)`. `source` is retained so training can weight recent-regime sources higher.

### 7.3 Depth targets

| Timeframe | Target | Purpose |
|---|---|---|
| 1d | 10+ years | Regime classifier, macro context |
| **1h** | **5–7 years** | **Primary ML + analog search timeframe** |
| 15m | 3 years | Intraday / day-trade models |
| 5m | 2 years | Short-horizon ML |
| 1m | rolling 6–12 months | Scalping only (selected assets) |

Grounded in Prado's *Advances in Financial ML* ch. 7 — purged k-fold + embargo needs hundreds of trades per fold for stable metrics.

## 8. Strategy Contract

**Stable across live, shadow, backtest, and ML inference.**

```python
class BaseStrategy(ABC):
    def __init__(self, name: str): ...
    @abstractmethod
    def analyze(self, df: pd.DataFrame, current_position: Optional[str] = None) -> Signal: ...

@dataclass
class Signal:
    signal_type: SignalType           # LONG | SHORT | CLOSE_LONG | CLOSE_SHORT | HOLD
    strength: float = 1.0             # 0.0 – 1.0
    reason: str = ""

class SignalType(Enum):
    LONG         = "LONG"
    SHORT        = "SHORT"
    CLOSE_LONG   = "CLOSE_LONG"
    CLOSE_SHORT  = "CLOSE_SHORT"
    HOLD         = "HOLD"
```

Strategies should be stateless between `analyze()` calls, or explicitly cache state keyed by `(symbol, interval)` (e.g., `outcome_arb`'s market-state cache). This lets the backtest engine replay history deterministically.

ML strategies plug in via `MLStrategy(BaseStrategy)` (Phase 10 of the overhaul) — `get_strategy("ml:<model_id>")` returns a loaded model wrapped as a strategy.

## 9. Exchange Integration

`core/exchange.py` is the only module that talks to Hyperliquid. Everything else (backtest, shadow, UI) routes through a `HyperliquidClient`-shaped interface.

`ExchangeShim` (planned, Phase 7) implements the same surface for the backtest engine, fed historical bars instead of live WS. `ShadowClient` (planned, Phase 11) wraps a testnet `HyperliquidClient` for shadow mode.

Key methods:

- `place_market_order(symbol, is_buy, size_usd, leverage)`
- `place_limit_order(symbol, is_buy, size_usd, price, leverage)`
- `modify_order(order_id, new_price)` / `modify_stop(order_id, new_stop)`
- `cancel_order(order_id)` / `cancel_all()`
- `close_position(symbol)` / `close_all_positions()`
- `get_position(symbol)` / `get_all_positions()`
- `get_market_price(symbol)`
- `update_leverage(symbol, leverage, is_cross)`

HIP-3 markets are supported transparently via the `dex=` constructor parameter. HIP-4 outcome contracts are handled by `core/outcome_client.py`, not `exchange.py` — they have their own protocol nuances.

## 10. Risk Management

### 10.1 Current (`core/risk_manager.py`)

- `can_trade()` — daily P&L vs `MAX_DAILY_LOSS_USD`.
- `can_open_position(n_current)` — `n_current < MAX_OPEN_POSITIONS`.
- `check_position_exit(entry, current, is_long)` — returns `"stop_loss"`, `"take_profit"`, or `None`.

### 10.2 Planned (Phase 2 + 11 overhaul)

See `OVERHAUL_PLAN.md` §13.

- **Keychain** — OS vault via Tauri `keyring` plugin. `.env` fallback only in dev mode.
- **Kill switch** — `Ctrl+Shift+Q` or titlebar button → cancel-all + flatten-all + disable-slots. Fat-finger guard (type "KILL" or hold 2s).
- **Aggregate exposure cap** — `MAX_AGGREGATE_EXPOSURE_USD` enforced across all slots + pending.
- **Confirmation modals** — above `confirm_above_usd` (default $1000) and `confirm_modify_pct` (default 20%).
- **Audit log** — append-only SQLite (`audit_log` table), schema triggers block UPDATE/DELETE.
- **Shadow mode** — per-slot toggle running strategy in parallel on testnet; divergence alerts.

## 11. HIP-4 Outcome Markets (first-class v1)

Equal-status surface alongside the chart workspace, **not a tab-deep feature**.

- **Board view** — active markets grouped by category (crypto / politics / sports / macro), sortable by resolution date / implied prob / volume / model edge.
- **Detail view** — probability curve (price bounded [0,1]), resolution rule header, order book, news feed (filtered by event tags), pricing-model theoretical overlay, edge panel, trade panel.
- **Tape storage** — `data/parquet/outcomes/market_id=<id>/year=<y>/part-000.parquet` with fields `timestamp, price, volume, implied_prob, best_bid, best_ask, event_id`.
- **Slots** — `OutcomeSlot` parallel to `PerpSlot`, runs `outcome_arb` or `outcome_ml:<model_id>` via the same `SlotRunner` interface.
- **ML** — per-category models train on all historical outcome markets (e.g., "crypto event + X days to resolve + Y implied prob → forward prob change").

## 12. Research + ML Pipeline

### 12.1 Research

Pure-function studies → `StudyResult (DataFrame + charts + summary)`:

- Correlation matrix (full universe × interval).
- Cointegration pair finder (Johansen, Engle-Granger).
- Seasonality heatmaps (hour / day-of-week / month).
- Regime classifier (HMM or rule-based).
- Event studies (FOMC, CPI, earnings, HIP-4 resolutions).
- Funding-vs-price correlates.
- Volatility regime buckets.
- Outcome-market news impact.

UI: study form → run → view → save to markdown notebook (exportable to HTML/PDF).

### 12.2 ML

- **Feature store** — versioned per asset + interval (`feature_set=core_v1`).
- **Labelers** — `forward_return_n`, `triple_barrier(pt, sl, h)`, `direction_n`, `vol_adjusted_return`, `outcome_resolution_label`.
- **CV** — purged k-fold + embargo (AFML ch. 7). Embargo bars = horizon length, prevents train-test leakage.
- **Models** — XGBoost classifier (baseline), logreg, random forest, LSTM optional.
- **Registry** — `data/models/<family>/<timestamp>/` with `model.pkl`, `features.json`, `label.json`, `metrics.json`, `config.json`.
- **Inference** — `MLStrategy(BaseStrategy)` loads a model card and emits `Signal`s via `analyze()`. Plugs into the same factory as rule-based strategies.

## 13. Analog / Pattern Search (first-class v1)

"Find past windows that look like now; show what happened next."

Two retrieval modes, both enabled:

- **DTW** — brute-force dynamic time warping with LB_Keogh pruning over z-scored windows. Classic, interpretable.
- **Embedding** — small 1D-conv autoencoder → 64-dim bottleneck → FAISS IVF-PQ. Sub-10 ms queries on 1M windows.

For every match, forward returns are aggregated at `{1, 5, 10, 20, 50}` bars. UI renders:

- Current window chart + top-N match grid.
- Forward-return distribution plot (histogram + density).
- Summary stats: median, IQR, hit rate, sharpe, sample count.

As an ML feature: `AnalogDistributionFeature` runs a strict-no-leakage analog query at each row, returning aggregate outcomes as model inputs.

## 14. UI Architecture (v1.0 target)

### 14.1 Desktop shell

Tauri 2 + React 19 + TypeScript + Vite. Tauri manages:

- FastAPI sidecar process lifecycle.
- OS keychain plugin.
- Native notifications.
- Auto-updater.
- Window / menu / tray.

### 14.2 Layout

- Left sidebar: workspace switcher.
- Main area: active workspace.
- Right inspector: context panel.
- Titlebar: connection status + always-visible kill switch.

### 14.3 Workspaces

- **Chart workspace** — `lightweight-charts` price pane + indicator subpanes + SVG markup layer. Grid of 1/2/4 charts. Replay mode.
- **Outcome workspace** — HIP-4 board + detail.
- **Slot manager** — perp + outcome slots, per-slot mini-chart + advanced config.
- **Backtest lab** — form → live-animated run → results + chart overlay.
- **Research notebook** — study picker + saved notebooks.
- **Analog search** — query + match grid + distribution plots.
- **ML training lab** — config → run → model card → promote to slot.
- **News** — live feed + alerts.
- **Audit log viewer** — filterable, exportable.
- **Settings** — keychain, slot defaults, confirmation thresholds, notifications.

## 15. Data Flow Diagrams

Full data-flow diagrams live in `OVERHAUL_PLAN.md` §14 (live trading, chart drag, analog query, backtest, outcome markets, ML training). This section links to those rather than duplicating — that document is load-bearing for any v1 work.

## 16. Testing Philosophy

### 16.1 Current

No real test suite. `test_setup.py` + `test_trade.py` are ad-hoc verification scripts.

### 16.2 Target (Phase 0 onward)

**Pytest suite under `tests/`**, mirroring source layout:

- `tests/unit/core/` — exchange / market-data / risk mocked tests.
- `tests/unit/strategies/` — **golden-signal tests**: OHLCV fixture → expected `Signal` stream. **Gate merges on zero drift.**
- `tests/unit/backend/` — FastAPI routes + services (Phase 2+).
- `tests/integration/` — end-to-end bot loops against a mocked exchange.
- `tests/e2e/` — Playwright against the Tauri UI (Phase 3+).

**Golden hand-calc philosophy**, borrowed from StruxDraft — every strategy has a frozen reference output for a canonical input. Any code change that breaks a golden is evaluated deliberately; the golden either moves with intent or the change is rejected. This is the verification wall.

## 17. Conventions

- **No keys in code, logs, or committed `.env`.** `.env` is `.gitignore`d. Phase 2 moves keys to OS keychain.
- **Strategy contract is immutable.** `analyze(df, current_position) -> Signal`. Do not change the signature. If you think you need to, add a new strategy subclass with extra inputs and compose.
- **Strategies should be stateless** between calls, or explicitly cache state keyed by `(symbol, interval)`. Backtest replays history; state keyed to wall-clock time breaks it.
- **`core/` is reusable infrastructure.** New app code belongs in `backend/` (Phase 0+), never in `dashboard.py` or `bot.py`.
- **No hardcoded market lists.** `UniverseManager` discovers markets dynamically from Hyperliquid.
- **No hardcoded fees / funding / leverage caps.** Read from the exchange metadata or a database.
- **HIP-4 outcomes are first-class.** Slot, backtest, and ML subsystems treat `PerpSlot` and `OutcomeSlot` uniformly via the `SlotRunner` interface.
- **Changelog discipline.** Append to `Changelog.txt` after any meaningful change. Never edit prior entries.
- **Numbered sections.** Design and overhaul docs use numbered sections so code comments can reference them (`see Design.md §8` or `see OVERHAUL_PLAN.md §13.2`).

## 18. Glossary

- **HIP-3** — Hyperliquid Improvement Proposal 3: builder-deployed perps. Opened the protocol to third parties (trade.xyz, etc.) launching their own perp markets with custom oracles and assets. Live on mainnet since Oct 2025.
- **HIP-4** — Hyperliquid Improvement Proposal 4: outcome contracts (binary / bounded prediction markets). Testnet live Feb 2026, mainnet rolling out.
- **Slot** — a single automated trading configuration (symbol + interval + strategy + risk parameters + size). The bot runs up to 5 concurrently.
- **Analog / pattern search** — query the historical dataset for windows matching the current market shape; surfaces forward-return distributions.
- **Shadow mode** — running a strategy in parallel against testnet while it trades live on mainnet, for A/B testing without capital risk.
- **Purged k-fold + embargo** — time-series-correct cross-validation (López de Prado, AFML ch. 7). Purges training samples that overlap a fold's horizon; embargoes a buffer of bars after each test fold to prevent leakage.
