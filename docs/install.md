# Install Guide

The fastest path to a working desktop install. Three minutes, two clicks.

---

## Option A — pre-built MSI (Windows)

This is what most users want.

### Step 1 · Download

1. Go to the project's **[Releases page](../../releases)**.
2. Download the latest `Hyperliquid Bot_<version>_x64_en-US.msi` file (~143 MB).

> **Note on releases:** the MSI is too large to ship inside the git tree (143 MB), so it lives on GitHub Releases instead. Each tagged version of the project gets a release with the MSI attached. If no Releases exist yet, build it yourself with Option B below.

### Step 2 · Run the installer

1. Double-click the `.msi` file.
2. **Windows SmartScreen warning:** "Microsoft Defender SmartScreen prevented an unrecognized app from starting." This appears because the binary isn't code-signed (a $100/year cert nobody bothers with on a personal project). Click **More info → Run anyway**.
3. The Tauri MSI wizard appears. Click Next → Next → Install. Defaults are fine.
4. Done. Look for "Hyperliquid Bot" in the Start menu.

### Step 3 · First launch

1. Click the Start menu icon. The Tauri window opens immediately.
2. The first launch waits **5-15 seconds** while the bundled Python runtime extracts itself to `%TEMP%\_MEI…\`. The dashboard top-right shows a red "backend down" indicator during this window — this is normal.
3. Subsequent launches are 1-3 seconds.
4. The Sidebar → **Tutorial** tab walks you through the rest.

### What it installs

- `C:\Program Files\Hyperliquid Bot\hyperliquid-bot.exe` — the desktop shell
- `C:\Program Files\Hyperliquid Bot\backend-sidecar.exe` — the bundled Python sidecar (140 MB)
- Start menu shortcut + uninstaller

User data is created on first launch under `%LOCALAPPDATA%\hyperliquid-bot\`:
- `data\` — SQLite + Parquet lake + settings + ML models
- `logs\` — boot log + structured backend log

The installer does **not** modify the system PATH or add services. Uninstall via Control Panel → Apps removes the binaries. To wipe data, delete `%LOCALAPPDATA%\hyperliquid-bot\` manually.

---

## Option B — build from source

If you don't trust the published MSI (fair) or want to customize the build, build it yourself.

### Prerequisites — install once

| Tool | Why | Where |
|---|---|---|
| Python 3.12 | sidecar build via PyInstaller | https://www.python.org/downloads/windows/ — check "Add to PATH" |
| Node 20 LTS | UI build via Vite + npm | https://nodejs.org/en/download |
| Rust (MSVC) | Tauri shell compile | https://rustup.rs/ — accept the VS 2022 Build Tools prompt |
| WebView2 runtime | UI runtime | preinstalled on Windows 11; [Evergreen runtime](https://developer.microsoft.com/microsoft-edge/webview2/) for Win10 |

Total prereq install time: ~10 minutes (mostly waiting on VS Build Tools).

### Build

From a fresh PowerShell in the cloned repo:

```powershell
.\scripts\build_windows.ps1
```

This script:
1. Creates `.venv` if missing → installs `requirements.txt` + PyInstaller
2. Runs `pyinstaller backend-sidecar.spec` → produces `dist/backend-sidecar.exe`
3. Copies the sidecar into `ui/src-tauri/binaries/backend-sidecar-x86_64-pc-windows-msvc.exe`
4. Runs `npm install` in `ui/`
5. Runs `npm run tauri:build` → produces the MSI + NSIS installer

Build time: **~10 minutes on a clean cache**, **~2 minutes on incremental rebuilds**.

Output:
- MSI: `ui\src-tauri\target\release\bundle\msi\Hyperliquid Bot_<ver>_x64_en-US.msi`
- NSIS setup.exe: `ui\src-tauri\target\release\bundle\nsis\Hyperliquid Bot_<ver>_x64-setup.exe`

Take either one.

### Cross-build from WSL

If you develop on Linux/WSL but build for Windows:

```bash
./scripts/sync_to_windows.sh --build
```

This rsyncs the repo to `C:\Projects\hyperliquid-bot\` (via the WSL `/mnt/c` mount), then shells into PowerShell to run `build_windows.ps1`. The Windows-side prereqs above still need to be installed.

---

## After install: API key setup

Three providers ship with starter keys baked in (FRED + Alpha Vantage):

| Provider | Free tier | Add via |
|---|---|---|
| **FRED** (macro data) | unlimited, free | [register here](https://fred.stlouisfed.org/docs/api/api_key.html) |
| **Alpha Vantage** (stocks) | 25 req/day | [register here](https://www.alphavantage.co/support/#api-key) |
| **CoinGecko** (crypto) | no key needed for free tier | n/a |
| **CryptoCompare** (crypto deep history) | optional, free | https://www.cryptocompare.com/ |
| **Plaid** (Balances tab — Fidelity/Robinhood/etc.) | free up to 100 items | https://dashboard.plaid.com/ |
| **E*Trade** (Balances tab) | requires dev app approval (~1-2 days) | https://developer.etrade.com |
| **Telegram** (Live Squawk) | no key needed for public-channel scrape | n/a |

Open Sidebar → **API Keys** to add or update any of these.

---

## After install: connect your Hyperliquid wallet

Two modes:

### Mode 1 — read-only (no trading)

Sidebar → **Wallet** → paste your master Hyperliquid wallet address (`0x...`). Save. The app immediately starts pulling:

- Live positions (with mark, liq, leverage, unrealized PnL)
- Trade history (last 200 fills)
- Cumulative realised PnL chart on the Dashboard

This works for **any** Hyperliquid address — track yours, a friend's, or a public whale wallet.

### Mode 2 — trading enabled

Sidebar → **Vault** → enter `wallet_address` + `private_key`. The private key is stored in the OS keychain (Windows Credential Manager), never in a file. Click **Unlock**. After unlock:

- Quick Trade panel on Dashboard executes real orders
- Slot bots actually trade
- Kill Switch flattens real positions

This is the **same `private_key + wallet_address` flow** that the legacy `bot.py` and `dashboard.py` use — so any `.env` you already have for those will work here verbatim.

---

## Updating the app

When a new version ships:

1. Close the running app — system tray + Task Manager → kill `hyperliquid-bot.exe` and `backend-sidecar.exe`. (Build #6 onward auto-kills any leftover sidecar; older builds need the manual taskkill.)
2. Download the new MSI.
3. Double-click — the wizard does an upgrade install over the existing one. User data is preserved.
4. Launch from Start menu.

---

## Uninstalling

Control Panel → Apps & features → "Hyperliquid Bot" → Uninstall.

To also remove user data: delete `%LOCALAPPDATA%\hyperliquid-bot\`.

---

## See also

- [`docs/getting_started.md`](getting_started.md) — first-time-user walkthrough (after install)
- [`docs/building.md`](building.md) — full build pipeline details
- [`internal_docs/trading_flow_audit.md`](../internal_docs/trading_flow_audit.md) — UX audit + known gaps
- [`README.md`](../README.md) — feature list + project overview
