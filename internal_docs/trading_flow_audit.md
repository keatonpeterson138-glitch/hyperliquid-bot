# Trading Flow Audit

End-to-end walkthrough of how a user goes from "just launched the app" to
"running a real trade", with every rough edge documented. Date: 2026-04-20.

---

## 1 · First launch (cold start)

**Observed:** Sidecar takes 5-15 seconds to boot on first launch while
PyInstaller extracts ~400 MB of Python runtime to `%TEMP%\_MEI…\`. During
that window the Dashboard shows "backend down" in the top-right dot.

**Gap:** No explicit "starting services..." indicator. User sees a red dot
and thinks something's broken.

**Fix (small, high-impact):** Dashboard top area → "Warming up: X/N services
ready" bar. Poll `/health` + component-status endpoints during boot, hide
once all green.

## 2 · API keys

**Observed:** Pre-loaded FRED + Alpha Vantage keys auto-hydrate from the
bundled `credentials_seed.json`. Sidebar → API Keys shows them masked.

**Gap:** No test-fire button per key. User has to open FRED Explorer or a
chart and wait for it to fail to know if a key is bad.

**Fix:** "Test" button per credential row that hits `/diagnostics/sources?name=X`
for that provider only. Green check or red X inline.

## 3 · Wallet (Hyperliquid perps)

**Current state:** Two paths — Vault page for raw-private-key entry (OS
keychain) OR the WalletPage now supports read-only tracking just by
pasting the master address (enables positions + history + PnL chart
without any keys).

**Gap (being addressed in the next push):** MetaMask-based agent wallet
flow. Today if the user wants to trade (not just watch), they have to
enter a raw private key through the Vault page. That's unfriendly for
non-technical users.

**Fix — design of the agent flow:**
1. WalletPage → "Connect MetaMask" → `window.ethereum.request({ method: "eth_requestAccounts" })`.
2. User picks the account; app stores the address via `PUT /wallet/address`.
3. Backend endpoint `POST /vault/agent/prepare` → generates a new secp256k1
   keypair in memory, returns `{ agent_address, nonce }`.
4. Frontend builds the Hyperliquid EIP-712 "ApproveAgent" typed-data
   structure and asks MetaMask to sign (`eth_signTypedData_v4`).
5. Frontend submits `{ action, nonce, signature }` → backend endpoint
   `POST /vault/agent/complete`.
6. Backend forwards to Hyperliquid's `/exchange` endpoint, receives ack,
   persists the agent private key to the OS keychain via `KeyVault`.
7. After approval, every order signs with the agent key locally — no more
   MetaMask popups.

Keychain entry: `hyperliquid-bot.agent.<master_address>` →
`{ private_key, created_at, approved_action_hash }`.

This matches how trade.xyz and other Hyperliquid bots do it. Full control
stays with the master wallet — the agent can trade but cannot withdraw.
Revoke via Vault → "Revoke agent" which calls Hyperliquid's `ApproveAgent`
with zero address.

## 4 · Charts

**Observed:** Tiled 1/2/4/8 layouts, every tile independently configurable.
Workspace persists to `localStorage["charts.workspace.v1"]`. In-memory cache
on candle data means tab switches don't blank charts. Indicators (EMA 12/26/50/200,
RSI subpane, volume, log scale), overlays (compare multiple symbols rebased
to 100), chart-type toggle (candle/bar/line/area).

**Gap:** No way to convert a chart markup (trendline / horizontal level) into
an order ticket directly on the tile — the existing `/orders/from-markup`
flow works backend-side but the right-click / click handler isn't wired
on the tile.

**Fix:** Add `onMarkupContextMenu` handler in `ChartTile.tsx` → opens a small
"Trade this level" popover, pre-filling the QuickTradePanel with the markup's
price as a limit / SL.

## 5 · Slots (bots)

**Observed:** Backtested-preset panel shows 4 winners (Keltner + Williams %R
on SPY and QQQ, all 77-80% WR). "Add slot" instantiates as disabled; Start
button flips to enabled. Tick button manually fires a single decision cycle
for debugging.

**Gap:** No per-slot P&L. Without that, you can't tell which of your running
bots are actually making money.

**Fix:** Add `/slots/{id}/pnl` endpoint that filters fills by the slot's
`slot_id` tag + sums closed_pnl_usd. Show as a small line chart per slot card.

## 6 · Dashboard Quick Trade

**Observed:** Symbol picker from live HL universe, long/short toggle, size,
leverage, market/limit entry, SL/TP with quick-fill chips (-0.5%/-1%/-2%/-5%
for SL, +1%/+2%/+3%/+5%/+10% for TP), big colored submit button.

**Gap:** Orders land in local DB as pending until the vault is unlocked or
the agent wallet is wired. Frontend *does* communicate this clearly in the
footer ("Orders land pending…") but the user might still be confused why
nothing shows on Hyperliquid.

**Fix:** Clear "NOT YET LIVE — pending vault unlock" badge next to the Submit
button when `GET /vault/status` reports locked. Plus a "Connect wallet
first" CTA button that routes to WalletPage.

## 7 · Dashboard PnL chart

**Observed:** Cumulative realised P&L line with 1D / 1W / 1M / 3M toggles.
Pulled from `GET /wallet/pnl` which computes from `userFills` closedPnl minus
fees. Green tint when cumulative > 0, red when < 0. Shows "no wallet address
set" banner + link when that's the case.

**Gap:** Doesn't plot unrealized P&L. Someone with 5 open positions at
current mark could look at a flat line and think "nothing's happening" when
actually they're up $500 on open positions.

**Fix:** Overlay unrealized P&L as a dashed line. Needs periodic
`clearinghouseState` polls (~5s) so it tracks mark price changes.

## 8 · Risk / kill switch

**Observed:** Title bar has the always-visible Kill Switch button (red,
confirmation modal, flattens all + cancels all + disables every slot). Audit
log records every action, append-only, UI-uneditable.

**Gap:** No per-asset max loss. If Gold runs against you hard, the global
kill switch flattens everything including unrelated winning positions.

**Fix:** Per-slot or per-asset stop-loss threshold that triggers a reduce-only
close for just that asset.

## 9 · Logs / diagnostics

**Observed:** `%LOCALAPPDATA%\hyperliquid-bot\logs\boot.log` captures every
sidecar launch; `backend.log` has rotating structured logs. Both accessible
via file explorer.

**Gap:** No in-app log viewer. User has to open Notepad to diagnose issues.

**Fix:** Sidebar → Settings → Advanced → "View logs" button opens a modal that
tails `/logs` endpoint in real-time.

---

## Summary of top-priority fixes (for the next push)

1. **MetaMask + agent wallet flow** (wallet page) — unblocks non-technical
   users from trading at all.
2. **Chart markup → order ticket** (chart tile right-click) — closes the
   chart-to-order UX loop.
3. **"NOT LIVE" badge on Quick Trade** when vault is locked — prevents
   "why didn't my order go through?" confusion.
4. **Per-slot PnL on the Slots page** — tells the user which bots are
   actually earning their slot allocation.
5. **In-app log viewer** — eliminates the "open Notepad" step for every
   diagnostic question.
