# Hyperliquid Trading Bot

Desktop trading app for [Hyperliquid](https://hyperliquid.xyz/) — perps, HIP-3 stocks/commodities/indices, and HIP-4 prediction markets. Native installer for Windows. Tauri + React UI on top of a Python FastAPI sidecar.

**Status:** v0.2 (release candidate). All Phase 0–13 work complete: backtested presets, MetaMask-free vault flow (uses Hyperliquid's standard `private_key` + `wallet_address`), live position + PnL tracking, in-app tutorial, 423 tests green.

---

## Download & install

### Windows — one-click installer

> **➡ Download: [HyperliquidBot-0.2.0-Setup.msi](https://github.com/keatonpeterson138-glitch/hyperliquid-bot/releases/latest/download/HyperliquidBot-0.2.0-Setup.msi) (143 MB)**
>
> Or browse all versions on the **[Releases page](https://github.com/keatonpeterson138-glitch/hyperliquid-bot/releases)**.

1. Click the link above to download the `.msi`.
2. Double-click the downloaded file.
3. Windows SmartScreen will warn "publisher unknown" — click **More info → Run anyway** (the installer isn't code-signed; that's a $100/year cert nobody bothers with on a personal project — see "Build from source" below if you don't trust the upload).
4. Follow the install wizard. Defaults are fine.
5. Launch "Hyperliquid Bot" from your Start menu.
6. First launch takes ~15 seconds while the bundled Python runtime extracts. After that, instant.

**That's it** — the app handles everything else (auto-creates the data folder, seeds preloaded API keys, loads the macro chart history in the background).

If MSI doesn't work for you, an NSIS `setup.exe` is attached to the same release as a fallback.

### Build from source (Linux / macOS / Windows)

See [`docs/building.md`](docs/building.md) for the full build pipeline. Short version:

```bash
git clone https://github.com/<you>/hyperliquid-bot
cd hyperliquid-bot

# WSL or Linux: run the cross-build script (rsyncs to a Windows mount, then PowerShell-builds the MSI)
./scripts/sync_to_windows.sh --build

# Or build natively on Windows from PowerShell:
.\scripts\build_windows.ps1
```

Output lands at `ui/src-tauri/target/release/bundle/msi/Hyperliquid Bot_<ver>_x64_en-US.msi`.

---

## What's in the install

The MSI bundles **everything** — no separate Python install, no `pip install`, no Node/Rust toolchain on the user's machine. After install you have:

| Component | Where | What it does |
|---|---|---|
| `hyperliquid-bot.exe` | `C:\Program Files\Hyperliquid Bot\` | Tauri shell — the actual desktop app you launch |
| `backend-sidecar.exe` | `C:\Program Files\Hyperliquid Bot\` | Frozen Python FastAPI server (uvicorn + pandas + duckdb + sklearn + yfinance + Hyperliquid SDK), 140 MB |
| WebView2 runtime | system | Chromium-based web view that renders the React UI (preinstalled on Windows 11) |

Per-user data lives at `%LOCALAPPDATA%\hyperliquid-bot\`:

| Path | What |
|---|---|
| `data\app.db` | SQLite — slots, audit log, credentials, balances, plaid, notes |
| `data\settings.json` | App settings |
| `data\models\` | Trained ML models |
| `data\parquet\ohlcv\` | OHLCV market-data lake (Hive-partitioned by symbol/interval/year) |
| `logs\boot.log` | Sidecar boot history (every launch appended) |
| `logs\backend.log` | Full structured logs (rotating, 5 MB × 3 backups) |

---

## System requirements

- **Windows 10/11 x64** with WebView2 (auto-installed on Win11; Win10 may need the [Evergreen runtime](https://developer.microsoft.com/microsoft-edge/webview2/)).
- ~500 MB free disk for the install + PyInstaller cache + initial market-data seed.
- An internet connection (for live prices, market data, and trading itself).
- A Hyperliquid wallet (testnet or mainnet) — see "Connect your wallet" below.

**Optional but recommended:**
- A FRED API key (free, [register here](https://fred.stlouisfed.org/docs/api/api_key.html)) for the macro Explorer. The MSI ships with a starter key preloaded, but it's rate-limited.
- An Alpha Vantage key (free, 25 req/day, [register here](https://www.alphavantage.co/support/#api-key)) for stock chart data.

---

## First-time setup walkthrough

After install, launch the app. The in-app **Tutorial** tab (sidebar → Other → Tutorial) is the canonical guide. Highlights:

### 1. Connect your Hyperliquid wallet (read-only)

Sidebar → **Wallet** → paste your master Hyperliquid wallet address (starts with `0x...`). Click Save. The app immediately starts pulling live positions, fill history, and PnL via Hyperliquid's public Info API. **No private key required for read-only mode** — works for any address you want to track.

### 2. Enable trading (private-key required)

Sidebar → **Vault** → enter `wallet_address` + `private_key`. Stored in the OS keychain (Windows Credential Manager), never in a file. Click **Unlock** to spin up the live `HyperliquidClient`. After unlock:
- Quick Trade panel on Dashboard executes real orders
- Slot bots (preset or custom) actually trade
- Kill Switch flattens real positions

This is the same `private_key + wallet_address` flow the legacy `bot.py` / `dashboard.py` use — fully reused.

### 3. Run a backtested preset

Sidebar → **Slots** → "Backtested presets" panel. Pick one of the 4 winners (Keltner Reversion / Williams %R on SPY or QQQ — all 77-80% WR, 1.86-3.17 Sharpe over 20 years; full report card in [`internal_docs/trading_presets.md`](internal_docs/trading_presets.md)). Click **+ Add slot** — created **disabled**. Click **Start** when you're ready.

### 4. Manual trade

Dashboard → **Quick Trade** panel. Symbol picker (full Hyperliquid universe), long/short toggle, size, leverage, market or limit, SL/TP with quick-% chips. Click the colored Submit button.

---

## Features

### Trading
- **5 backtested strategies** — `connors_rsi2`, `bb_fade`, `keltner_reversion`, `williams_mean_rev`, `gap_fill`. Each with a published walk-forward backtest: WR, Sharpe, max DD, return.
- **4 preset slots** ready to instantiate (highest WR pairs from the bench).
- **Quick Trade panel** — manual market/limit orders with bracket SL+TP.
- **Up to 8 concurrent slot bots**, each with own symbol / interval / strategy / risk.
- **Slot filters**: trailing stops, MTF confirmation, regime filter, ATR stops, loss cooldown, volume confirm, RSI guard.
- **Kill switch** in the title bar — flatten + cancel + disable everything in one click.

### Charts
- 1 / 2 / 4 / 8 tile workspace, persists across tab switches and app restarts.
- Chart types: candle / bar / line / area, log-scale toggle.
- Indicators: EMA 12/26/50/200, RSI(14) subpane, volume.
- Compare-mode overlays (multiple symbols rebased to 100).
- Markup tools: lines, horizontal levels, Fibonacci. Right-click → trade ticket.
- Live Hyperliquid WebSocket per tile.
- Symbol catalog covers HL crypto + HIP-3 perps (xyz:TSLA / cash:GOLD) + stocks (AAPL/NVDA/TSLA) + indices (^GSPC/^VIX) + FRED macro (DGS10/CPIAUCSL/M2SL).

### Wallet & PnL
- Live positions table — entry / mark / liq / leverage / margin / unrealized PnL.
- Live trade history — last 200 fills with closed PnL + fees.
- Cumulative realised-PnL chart on the Dashboard with **1D / 1W / 1M / 3M** toggles.
- All from Hyperliquid's `clearinghouseState` + `userFills` (read-only Info API).

### Data
- DuckDB catalog over a Parquet lake, Hive-partitioned by `symbol/interval/year`.
- Macro auto-seed on first launch — S&P, Nasdaq, WTI, Gold, Silver, BTC, ETH, SOL across 1d (20y) + 1h (1-3y).
- 8 sources stitched: Hyperliquid + Binance + Coinbase + yfinance + CryptoCompare + CoinGecko + FRED + Alpha Vantage.
- "Load history" button on Data Lab for on-demand backfill of any (symbol, interval).

### Research & ML
- Backtest engine (single-run + sweep + Monte Carlo).
- Triple-barrier ML labeling + purged k-fold CV (de Prado AFML).
- Optuna hyperparameter search.
- Analog / pattern search.
- FRED macro Explorer with 20 popular series + free-text search.

### Other
- Balances tab — multi-broker EoD equity (Plaid for Fidelity/Robinhood/etc.; E*Trade direct OAuth).
- Live Squawk — Telegram channel scraper (no auth).
- News panel — RSS + CryptoPanic poller.
- API Keys export/import for cross-machine setups.
- Append-only audit log of every order + config change (CSV exportable).
- 12-section in-app Tutorial.

---

## Safety defaults

- Vault locked at startup → no trading possible until you explicitly unlock.
- Kill Switch always visible in the title bar.
- Confirmation modals above configurable $ + % thresholds.
- Daily-loss circuit breaker.
- Aggregate exposure cap across slots.
- Append-only audit log (uneditable from the UI).
- Optional shadow mode — every live slot replays on testnet, divergence alerts.

---

## Strategies

| Name | Logic | Best for | Backtest WR |
|---|---|---|---|
| `connors_rsi2` | RSI(2) < 10 in SMA-200 uptrend, exit on first up-close | High-vol crypto on daily | ~53% (BTC), 47% (ETH) |
| `bb_fade` | Lower BB outside, ADX < 25 ranging filter | Range-bound assets | ~71-74% |
| `keltner_reversion` | Below lower Keltner + RSI(14) < 30 | Indices, daily | **80% (SPY), 79% (QQQ)** ✅ |
| `williams_mean_rev` | Williams %R < -90 in SMA-200 uptrend | Indices, daily | **78% (SPY/QQQ)** ✅ |
| `gap_fill` | Daily gap ≥ 0.5% with volume, fade to prior close | Liquid equities | varies |

Full report card with Sharpe / DD / trade count per (strategy × asset) in [`internal_docs/trading_presets.md`](internal_docs/trading_presets.md).

---

## Documentation

- **[in-app Tutorial tab](#)** — 12 sections, opens after install
- [`internal_docs/OVERHAUL_PLAN.md`](internal_docs/OVERHAUL_PLAN.md) — v1.0 architecture + roadmap
- [`internal_docs/PHASE_5p5_TO_12_PLAN.md`](internal_docs/PHASE_5p5_TO_12_PLAN.md) — phase 5-12 detailed plan
- [`internal_docs/Design.md`](internal_docs/Design.md) — product vision + subsystem overview
- [`internal_docs/Changelog.txt`](internal_docs/Changelog.txt) — append-only change log
- [`internal_docs/trading_presets.md`](internal_docs/trading_presets.md) — backtest report card
- [`internal_docs/trading_flow_audit.md`](internal_docs/trading_flow_audit.md) — UX audit + gap list
- [`docs/getting_started.md`](docs/getting_started.md) — user quickstart
- [`docs/building.md`](docs/building.md) — build pipeline (sidecar + Tauri)
- [`todo/path_to_v1.md`](todo/path_to_v1.md) — phase tracker
- [`CLAUDE.md`](CLAUDE.md) — AI-assistant quick reference

---

## Legacy Python CLI (still works)

The old single-slot CLI loop and Tkinter dashboard are still in the repo and still work — they predate the Tauri app and are useful for debugging or headless server runs:

```bash
pip install -r requirements.txt
cp .env.example .env  # fill in PRIVATE_KEY + WALLET_ADDRESS
python bot.py        # CLI loop
python dashboard.py  # Tkinter dashboard
```

The new Tauri app supersedes both for everyday use, but the wallet config is the same — `.env` keys you already have just plug into Sidebar → Vault.

---

## Troubleshooting

| Symptom | Likely cause + fix |
|---|---|
| App opens, says "backend down" | Wait 15-30 s on first launch (PyInstaller extracts ~400 MB to `%TEMP%`). Subsequent launches are 1-3 s. |
| 404 on every API call | Old sidecar still holding port 8787. Build #6+ auto-kills zombies; older builds need `taskkill /F /IM backend-sidecar.exe /T` first. |
| Charts show "no data" for a stock | yfinance backfill is async — give it 10-30 s on first fetch. After that it's cached locally. |
| FRED Explorer fails | Add a real FRED key in Sidebar → API Keys (the bundled starter key is rate-limited). |
| SmartScreen blocks the MSI | "More info → Run anyway" — the installer isn't code-signed. Or build it yourself from source. |
| `boot.log` shows `WinError 10048 / port 8787` | Another sidecar instance is already running. `taskkill /F /IM backend-sidecar.exe`. |
| Trading orders show "pending" forever | Vault isn't unlocked. Sidebar → Vault → Unlock. |

For anything else, check `%LOCALAPPDATA%\hyperliquid-bot\logs\boot.log` first — it logs every sidecar boot + crash with full stack traces.

---

## Disclaimer

For educational and research use. Crypto and equity-perp trading carry significant risk.

- Test thoroughly on testnet first.
- Never invest more than you can afford to lose.
- Past performance ≠ future results.
- The developers are not responsible for any financial losses.

## License

MIT.
