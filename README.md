# Hyperliquid Trading Bot

Automated perpetual futures + prediction-market trading bot for [Hyperliquid](https://hyperliquid.xyz/), with configurable strategies, multi-slot position management, risk management, and real-time notifications.

**Status:** v1.0 scope shipped — all 14 phases complete (Phases 0–13). 402 tests passing, ruff clean. Native cross-OS installer builds + final vault-gated exchange wiring are the remaining items before tagging the mainnet release. See [`internal_docs/OVERHAUL_PLAN.md`](internal_docs/OVERHAUL_PLAN.md) + [`internal_docs/PHASE_5p5_TO_12_PLAN.md`](internal_docs/PHASE_5p5_TO_12_PLAN.md) for the architecture, [`docs/getting_started.md`](docs/getting_started.md) for the user quickstart.

## Supported Markets

- **Native Hyperliquid perps** — BTC, ETH, SOL, HYPE, and ~100 other crypto perps.
- **HIP-3 builder-deployed perps** (via `trade.xyz` and other deployers):
  - **Stocks:** NVDA, TSLA, AAPL, MSFT, GOOGL, AMZN, META, HOOD, INTC, PLTR, COIN, NFLX, MSTR, AMD, TSM
  - **Indices:** SP500 (S&P-licensed, up to 50×), XYZ100 (Nasdaq-100)
  - **Commodities:** gold, silver, crude oil, corn, wheat
  - **FX** pairs
- **HIP-4 outcome contracts** — prediction markets (testnet live; mainnet rolling out).

## Features

### Trading
- Multiple built-in strategies: EMA crossover, RSI mean reversion, breakout, funding dip, outcome-market arbitrage.
- Up to **5 concurrent position slots**, each with its own symbol / interval / strategy / risk parameters.
- Per-slot filters: trailing stops, multi-timeframe confirmation, regime filter, ATR stops, loss cooldown, volume confirm, RSI guard.
- Timeframe-preset SL/TP/leverage recommendations (1m scalp → 1d position).

### Risk Management
- Stop-loss and take-profit per position.
- Daily loss circuit breaker.
- Max open positions cap.
- Mainnet + testnet support.

### Prediction Markets (HIP-4)
- Outcome contract discovery and pricing.
- `outcome_arb` strategy for theoretical-vs-market edge trading.
- Real-time monitoring and event tracking.

### Notifications
- Email alerts (SMTP).
- Telegram bot alerts.

### UI
- Current: Tkinter desktop dashboard (`dashboard.py`) — slot manager, live P&L, predictions board, news, logs, settings.
- Planned for v1.0: Tauri + React desktop app with TradingView-style charts, drawing tools, backtest lab, ML training, analog/pattern search, mainnet-grade hardening.

## Quick Start

### 1. Install

```bash
pip install -r requirements.txt
```

### 2. Configure

Copy `.env.example` to `.env` and set:

```ini
PRIVATE_KEY=<your wallet private key, no 0x prefix>
WALLET_ADDRESS=0x...
USE_TESTNET=true        # start on testnet!
SYMBOL=BTC
STRATEGY=ema_crossover
CANDLE_INTERVAL=1h
POSITION_SIZE_USD=100
MAX_LEVERAGE=3
```

For HIP-3 markets, use the `dex:symbol` format (e.g. `SYMBOL=xyz:TSLA`, `SYMBOL=cash:GOLD`) and set `DEX=xyz` or `DEX=cash` accordingly.

For multi-slot, configure `SLOT_1`..`SLOT_5` via the Settings tab in the dashboard, or edit `.env` directly:

```
SLOT_1=BTC|1h|ema_crossover|2.0|4.0|3|true|1000|{}|false|true|false|false|true|false|false|30|70
```

### 3. Run

CLI single-slot loop:

```bash
python bot.py
```

Desktop dashboard (recommended):

```bash
python dashboard.py
```

### 4. Test Setup

Before running live:

```bash
python test_setup.py    # verify credentials and exchange connectivity
python test_trade.py    # place + cancel a test order (testnet only)
```

## Strategies

| Name | Logic | Best For |
|---|---|---|
| `ema_crossover` | Buy when fast EMA crosses above slow; sell when it crosses below | Trending markets |
| `rsi_mean_reversion` | Buy oversold (RSI < 30), sell overbought (RSI > 70) | Range-bound markets |
| `breakout` | Buy on resistance break, sell on support break | Volatile markets with defined S/R |
| `funding_dip` | Fade extreme funding-rate moves on perps | Overheated / crashing funding |
| `outcome_arb` | HIP-4 prediction-market edge vs theoretical pricing model | Prediction markets |

Each strategy extends `BaseStrategy` in `strategies/base.py`. Add your own by subclassing and registering in `strategies/factory.py`:

```python
class MyStrategy(BaseStrategy):
    def analyze(self, df, current_position=None) -> Signal:
        # your logic
        return Signal(SignalType.LONG, strength=0.8, reason="my signal")
```

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `PRIVATE_KEY` | (required) | Wallet private key, hex, no `0x` prefix |
| `WALLET_ADDRESS` | (required) | Wallet address |
| `USE_TESTNET` | `true` | Testnet (recommended while testing) |
| `DEX` | `''` | HIP-3 dex (`''`, `cash`, `xyz`, …) |
| `SYMBOL` | `BTC` | Market symbol |
| `STRATEGY` | `ema_crossover` | Strategy name |
| `CANDLE_INTERVAL` | `1h` | `1m`, `5m`, `15m`, `1h`, `4h`, `1d` |
| `POSITION_SIZE_USD` | `100` | Position size |
| `MAX_LEVERAGE` | `5` | 1–50 |
| `STOP_LOSS_PCT` | `2.0` | Stop-loss % |
| `TAKE_PROFIT_PCT` | `4.0` | Take-profit % |
| `MAX_OPEN_POSITIONS` | `3` | Max concurrent positions |
| `MAX_DAILY_LOSS_USD` | `500` | Daily loss circuit breaker |
| `LOOP_INTERVAL_SEC` | `15` | Poll interval |
| `EMAIL_ENABLED` / `TELEGRAM_ENABLED` | `false` | Notifications toggle |
| `SLOT_1`..`SLOT_5` | empty | Multi-slot pipe-separated config |

## Project Layout

```
hyperliquid-bot/
├── bot.py                    ← CLI single-slot entrypoint
├── dashboard.py              ← Tkinter desktop dashboard (current UI)
├── config.py                 ← .env loader + slot parser
├── core/                     ← exchange + infra (reused in v1 overhaul)
├── strategies/               ← strategy plugins
├── gui/                      ← Tkinter tabs (v1 replaces with Tauri)
├── scripts/                  ← one-off ops utilities
├── internal_docs/            ← design + planning docs
├── todo/                     ← phase trackers + backlog
└── test_setup.py / test_trade.py  ← manual verification scripts
```

## Documentation

- [`internal_docs/OVERHAUL_PLAN.md`](internal_docs/OVERHAUL_PLAN.md) — v1.0 architecture + 12-phase roadmap.
- [`internal_docs/Design.md`](internal_docs/Design.md) — product vision, trading basis, and subsystem overview.
- [`internal_docs/Changelog.txt`](internal_docs/Changelog.txt) — append-only change log.
- [`todo/path_to_v1.md`](todo/path_to_v1.md) — phase-by-phase status tracker.
- [`CLAUDE.md`](CLAUDE.md) — AI-assistant quick reference.

## Safety

- **Always test on testnet first.** Hyperliquid testnet has a faucet (`python -m scripts.testnet_faucet`).
- **Never commit `.env`, private keys, or credentials.** `.env` is in `.gitignore`.
- **Start small on mainnet.** Position sizing and daily-loss caps exist for a reason — use them.
- **Review fills regularly.** The audit log (planned in Phase 2) will make this easier.

## Troubleshooting

- **"Configuration errors: PRIVATE_KEY must be set"** — copy `.env.example` to `.env` and fill in credentials.
- **"Failed to get market price"** — check internet and that the symbol exists (use `python discover_markets.py` to list available markets).
- **"Max positions limit reached"** — bump `MAX_OPEN_POSITIONS` or close existing positions.
- **Orders not executing** — confirm sufficient balance, correct leverage (Hyperliquid max 50×), correct network (testnet vs mainnet).
- **HIP-3 symbol not recognized** — HIP-3 symbols require `dex:symbol` format (e.g. `xyz:TSLA`). Set `DEX=xyz` in `.env`.

## Disclaimer

This bot is for educational and research purposes. Cryptocurrency and equity-perp trading carry significant risk.

- Test thoroughly on testnet before deploying real funds.
- Never invest more than you can afford to lose.
- Past performance does not guarantee future results.
- The developers are not responsible for any financial losses.

Use at your own risk.

## License

MIT.
