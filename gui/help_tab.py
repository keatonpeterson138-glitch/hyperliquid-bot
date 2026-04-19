"""Help tab – reference guide for all settings and strategy parameters."""
from __future__ import annotations
import tkinter as tk
from gui.theme import *
from gui.components import Card


# ── Content data ────────────────────────────────────────────────
_SECTIONS: list[dict] = [
    # ── Per-Slot Settings ───────────────────────────────────────
    {
        "title": "Per-Slot Settings",
        "intro": (
            "Each position slot runs independently with its own symbol, "
            "strategy, and risk settings.  You can have up to 5 slots active."
        ),
        "items": [
            ("Symbol",
             "The asset to trade (e.g. BTC, ETH, SOL).  "
             "HIP-3 commodities/stocks use the cash: prefix (cash:GOLD, cash:TSLA).  "
             "TradeXYZ assets use the xyz: prefix (xyz:TSLA, xyz:SP500, xyz:GOLD)."),
            ("Timeframe",
             "Candle interval the strategy analyzes.  Changing this auto-fills "
             "recommended SL / TP / Leverage defaults.\n"
             "  • 1m / 5m  →  Scalping (tight SL, high leverage)\n"
             "  • 15m       →  Day-trade\n"
             "  • 1h / 4h  →  Swing trade\n"
             "  • 1d         →  Position trade (wide SL, low leverage)"),
            ("Strategy",
             "Which entry algorithm to use for this slot.  "
             "See the strategy-specific sections below for parameter details."),
            ("Size$",
             "Position size in USD for this slot.  Each slot can have a different "
             "size so you can allocate more capital to higher-conviction setups."),
            ("SL%  (Stop Loss %)",
             "How far the price must move against you before the on-chain "
             "stop-loss trigger order fires.\n"
             "Example: SL 2% on a $100 LONG at $50,000 → SL triggers at $49,000.\n"
             "Lower = tighter risk (stopped out sooner).  Higher = more room to breathe."),
            ("TP%  (Take Profit %)",
             "How far the price must move in your favour before the on-chain "
             "take-profit trigger order fires.\n"
             "Example: TP 4% on a $100 LONG at $50,000 → TP triggers at $52,000.\n"
             "Aim for TP > SL so your winners outpace your losers (positive R:R)."),
            ("Lev  (Leverage)",
             "Multiplier applied to your margin.  5× Lev on a $100 position "
             "controls $500 of exposure.\n"
             "Higher leverage amplifies both gains AND losses — and increases "
             "liquidation risk.  Recommended:\n"
             "  • Scalp  1m–5m   →  7–10×\n"
             "  • Day    15m       →  5×\n"
             "  • Swing  1h–4h   →  2–3×\n"
             "  • Position 1d     →  1×"),
        ],
    },
    # ── EMA Crossover ───────────────────────────────────────────
    {
        "title": "Strategy: EMA Crossover",
        "intro": (
            "Tracks a fast and a slow Exponential Moving Average.  "
            "A LONG entry fires when the fast EMA crosses above the slow EMA; "
            "a SHORT entry fires on the reverse crossover."
        ),
        "items": [
            ("EMA Fast  (default 9)",
             "Number of candles for the fast (reactive) moving average.\n"
             "Lower → more responsive, more trade signals, more false positives.\n"
             "Higher → smoother, fewer but higher-quality signals."),
            ("EMA Slow  (default 21)",
             "Number of candles for the slow (baseline) moving average.\n"
             "A wider gap between Fast and Slow (e.g. 5 / 50) means fewer, "
             "more selective signals.\n"
             "A narrow gap (e.g. 8 / 13) yields more frequent entries."),
        ],
    },
    # ── RSI Mean Reversion ──────────────────────────────────────
    {
        "title": "Strategy: RSI Mean Reversion",
        "intro": (
            "Uses the Relative Strength Index to detect overbought / oversold "
            "conditions.  Enters LONG when RSI dips below the Oversold level "
            "and SHORT when RSI rises above the Overbought level."
        ),
        "items": [
            ("RSI Period  (default 14)",
             "How many candles are used to calculate RSI.\n"
             "Lower (e.g. 7) → RSI swings more wildly, triggers more often.\n"
             "Higher (e.g. 21) → smoother RSI, fewer but stronger signals."),
            ("Oversold  (default 30)",
             "RSI below this value → LONG entry.\n"
             "Lower value (e.g. 20) = more selective — only enters on extreme dips.\n"
             "Higher value (e.g. 40) = enters earlier, more trades."),
            ("Overbought  (default 70)",
             "RSI above this value → SHORT entry.\n"
             "Higher value (e.g. 80) = more selective — only on extreme pumps.\n"
             "Lower value (e.g. 60) = enters earlier, more trades."),
        ],
    },
    # ── Breakout ────────────────────────────────────────────────
    {
        "title": "Strategy: Breakout",
        "intro": (
            "Identifies support and resistance from recent highs/lows.  "
            "Enters LONG when price breaks above resistance and SHORT when "
            "it breaks below support."
        ),
        "items": [
            ("Lookback  (default 20)",
             "Number of candles to scan for support / resistance levels.\n"
             "More candles → stronger levels but fewer breakout opportunities.\n"
             "Fewer candles → weaker levels, more frequent signals."),
            ("Breakout %  (default 0.5)",
             "How far past the level price must close to count as a valid breakout, "
             "expressed as a percentage of the range (resistance – support).\n"
             "Higher → filters out more fakeouts, fewer entries.\n"
             "Lower → catches breakouts earlier, more false signals."),
        ],
    },
    # ── Global Settings ─────────────────────────────────────────
    {
        "title": "Global Settings",
        "intro": "Settings that apply to the bot as a whole, not to individual slots.",
        "items": [
            ("Loop Interval (sec)",
             "How often the bot iterates through all active slots (in seconds).\n"
             "15 s is a good default.  Going below 5 s may cause rate-limit issues."),
            ("Max Daily Loss ($)",
             "If cumulative daily losses exceed this amount the bot will stop "
             "opening new positions for the rest of the day.\n"
             "Acts as a circuit breaker to protect your account."),
        ],
    },
    # ── How SL/TP Works ─────────────────────────────────────────
    {
        "title": "How Stop Loss & Take Profit Work",
        "intro": "",
        "items": [
            ("On-Chain Trigger Orders",
             "When the bot opens a position it immediately places two trigger "
             "orders directly on Hyperliquid:\n"
             "  1. A Stop-Loss order (reduce-only) at your SL% below/above entry.\n"
             "  2. A Take-Profit order (reduce-only) at your TP% above/below entry.\n\n"
             "These orders live on the exchange — if the bot crashes or disconnects, "
             "your SL and TP are still active and will execute."),
            ("Entry-Only Strategies",
             "Strategies only generate entry signals (LONG / SHORT).  They never "
             "close a position.  All exits happen through the on-chain SL/TP "
             "trigger orders.\n\n"
             "The only exception is critical news events, which auto-close all "
             "positions as a safety measure."),
        ],
    },
    # ── Trailing Stop Loss ──────────────────────────────────────
    {
        "title": "Trailing Stop Loss",
        "intro": (
            "When enabled on a slot, the stop-loss automatically ratchets "
            "closer to the current price as the trade moves in your favour.  "
            "This lets you lock in profit while still giving the trade room to run."
        ),
        "items": [
            ("How it works — LONG",
             "The bot tracks the highest price reached since entry (high-water mark).\n"
             "Each loop iteration it recalculates:  new_SL = high_water × (1 − SL%/100).\n"
             "If the new SL is higher than the current on-chain SL, the old SL order "
             "is cancelled and a new one is placed at the tighter level.\n\n"
             "Example: You go LONG at $100 with SL 2%.  Initial SL = $98.\n"
             "Price rises to $110 → new SL = $110 × 0.98 = $107.80.\n"
             "If price then drops to $107.80 the SL fires, locking in ~$7.80 profit."),
            ("How it works — SHORT",
             "Same logic inverted.  Tracks the lowest price since entry (low-water mark).\n"
             "new_SL = low_water × (1 + SL%/100).\n"
             "SL only moves DOWN (tighter) as price falls in your favour."),
            ("Enable / Disable",
             "Toggle the 'Trail SL' checkbox on each slot row in Settings.\n"
             "The SL% setting doubles as the trailing distance — the SL will always "
             "sit SL% away from the best price reached.\n\n"
             "The TP trigger order is unaffected — it stays at the original TP% level."),
            ("Notifications",
             "Every time the trailing SL moves, the bot logs the old → new SL price "
             "and sends a Telegram alert (if Telegram is enabled)."),
        ],
    },
    # ── Multi-Timeframe Confirmation ────────────────────────────
    {
        "title": "Multi-Timeframe Confirmation",
        "intro": (
            "Adds a trend-alignment filter before entries.  Before the bot opens "
            "a trade on the slot's timeframe, it checks a higher timeframe to "
            "confirm the broader trend agrees with the signal direction."
        ),
        "items": [
            ("How it works",
             "The bot fetches candles on a higher timeframe and calculates the 21-period "
             "EMA.  If the EMA is rising → higher-TF trend is bullish; if falling → bearish.\n\n"
             "  • LONG signal  → only allowed if higher-TF EMA is rising\n"
             "  • SHORT signal → only allowed if higher-TF EMA is falling\n\n"
             "If the higher TF disagrees, the entry is blocked and logged as 'EMA misaligned'."),
            ("Timeframe Mapping",
             "Each slot timeframe maps to a higher confirmation timeframe:\n"
             "  • 1m   →  15m\n"
             "  • 5m   →  1h\n"
             "  • 15m  →  4h\n"
             "  • 1h   →  4h\n"
             "  • 4h   →  1d\n"
             "  • 1d   →  (no higher TF — skipped)"),
            ("Enable / Disable",
             "Toggle the 'MTF' checkbox on each slot row in Settings.\n"
             "Enabled by default.  You can enable it for some slots and disable "
             "it for others — e.g. use MTF on scalp timeframes (1m/5m) but skip "
             "it on higher timeframes where the confirmation TF is too slow."),
            ("Fail-Safe Behaviour",
             "If the higher-TF candle data is unavailable or insufficient (< 22 candles), "
             "the check is skipped and the trade is allowed through.  This prevents "
             "the filter from permanently blocking trades due to data issues."),
        ],
    },
    # ── ADX Regime Filter ───────────────────────────────────────
    {
        "title": "ADX Regime Filter",
        "intro": (
            "Automatically detects whether the market is trending or ranging "
            "and only allows the appropriate strategy type to trade.  This "
            "prevents mean-reversion strategies from fighting trends, and "
            "trend-following strategies from whipsawing in choppy ranges."
        ),
        "items": [
            ("How it works",
             "The Average Directional Index (ADX) measures trend strength on a "
             "0–100 scale using 14-period smoothed directional movement:\n\n"
             "  • ADX > 25 → Trending market\n"
             "      Only EMA Crossover and Breakout strategies can enter.\n"
             "      RSI Mean Reversion is blocked.\n\n"
             "  • ADX < 20 → Ranging market\n"
             "      Only RSI Mean Reversion can enter.\n"
             "      EMA Crossover and Breakout are blocked.\n\n"
             "  • ADX 20–25 → Transition zone\n"
             "      All strategies are allowed (no filter applied)."),
            ("Why it matters",
             "Your losing streak on 1m RSI mean reversion was likely caused by a "
             "trending market.  RSI stays pegged at overbought/oversold during "
             "strong trends, generating false reversal signals.  The ADX filter "
             "would have blocked those entries because ADX was above 25."),
            ("Enable / Disable",
             "Toggle the 'ADX' checkbox on each slot row in Settings.  "
             "Strategy type is detected automatically from the strategy name."),
        ],
    },
    # ── ATR-Based Stops ─────────────────────────────────────────
    {
        "title": "ATR-Based Stops",
        "intro": (
            "Replaces fixed-percentage SL/TP with volatility-adjusted levels "
            "derived from the Average True Range (ATR).  Stops automatically "
            "widen in volatile markets and tighten in calm markets."
        ),
        "items": [
            ("How it works",
             "When ATR-SL is enabled, the bot calculates ATR(14) on the current "
             "timeframe at the moment of entry:\n\n"
             "  • Stop Loss  = 2 × ATR  (distance from entry)\n"
             "  • Take Profit = 3 × ATR  (1.5:1 reward-to-risk ratio)\n\n"
             "These are converted to percentages and used instead of the fixed "
             "SL% and TP% values in your slot config.\n\n"
             "Example: BTC at $95,000 with ATR = $500\n"
             "  SL = 2×$500 = $1,000 → 1.05%\n"
             "  TP = 3×$500 = $1,500 → 1.58%"),
            ("Safety Bounds",
             "ATR-derived percentages are clamped to sensible limits:\n"
             "  • SL: 0.1% – 15%\n"
             "  • TP: 0.15% – 20%\n\n"
             "This prevents absurd levels during extreme volatility spikes."),
            ("Interaction with Trailing SL",
             "If both ATR-SL and Trail SL are enabled, the trailing stop starts "
             "at the ATR-calculated SL level and then ratchets tighter as price "
             "moves in your favour."),
            ("Enable / Disable",
             "Toggle the 'ATR-SL' checkbox on each slot.  When disabled, "
             "the fixed SL% and TP% from your slot config are used as before."),
        ],
    },
    # ── Loss Cooldown ───────────────────────────────────────────
    {
        "title": "Loss Cooldown",
        "intro": (
            "Pauses a slot after 3 consecutive losing trades, preventing "
            "the bot from bleeding capital during unfavourable conditions."
        ),
        "items": [
            ("How it works",
             "The bot tracks consecutive stop-loss hits per slot.  When a "
             "position is closed by an on-chain SL/TP and the exit was a loss "
             "(price moved against entry), the counter increments.\n\n"
             "After 3 consecutive losses, the slot enters a 30-minute cooldown.  "
             "During cooldown, all entry signals for that slot are ignored.\n\n"
             "The counter resets to 0 on any winning trade."),
            ("Why 3 losses / 30 minutes?",
             "Three back-to-back losses strongly suggests the strategy disagrees "
             "with current market conditions.  A 30-minute pause allows the "
             "market structure to shift — often enough for a regime change "
             "from trending to ranging (or vice versa)."),
            ("Enable / Disable",
             "Toggle the 'Cooldown' checkbox on each slot.  The cooldown counter "
             "resets when you restart the bot."),
        ],
    },
    # ── Volume Confirmation ─────────────────────────────────────
    {
        "title": "Volume Confirmation",
        "intro": (
            "Adds a volume filter that blocks entries unless the current "
            "candle's volume exceeds the recent average, confirming market "
            "conviction behind the move."
        ),
        "items": [
            ("How it works",
             "Before entering a trade, the bot checks if the current candle's "
             "volume is at least 1.5× the 20-period average volume.\n\n"
             "  • Volume ≥ 1.5× avg → entry allowed\n"
             "  • Volume < 1.5× avg → entry blocked\n\n"
             "High volume on a signal candle indicates real participation, "
             "reducing false breakouts and weak reversals."),
            ("Fail-Safe",
             "If volume data is unavailable (some HIP-3 pairs may not "
             "report volume), the filter is skipped and the entry is allowed."),
            ("Enable / Disable",
             "Toggle the 'Vol' checkbox on each slot.  Works independently "
             "of all other filters — you can combine it with ADX, MTF, etc."),
        ],
    },
    # ── RSI Exhaustion Guard ────────────────────────────────────
    {
        "title": "RSI Exhaustion Guard",
        "intro": (
            "Prevents EMA crossover and breakout strategies from entering "
            "at RSI extremes — blocking shorts at oversold bottoms and "
            "longs at overbought tops."
        ),
        "items": [
            ("How it works",
             "Before entering a trade on an EMA crossover or breakout signal, "
             "the bot calculates RSI(14) on the same candle data:\n\n"
             "  • SHORT signal + RSI < 30 → Blocked (oversold = likely bottom)\n"
             "  • LONG signal + RSI > 70 → Blocked (overbought = likely top)\n"
             "  • Otherwise → entry allowed\n\n"
             "This catches the classic failure mode where a lagging EMA cross "
             "fires after the bulk of a move is already over."),
            ("When it applies",
             "Only activates on non-RSI strategies (EMA crossover, breakout). "
             "RSI mean-reversion slots are not affected since they already use "
             "RSI thresholds for entry logic."),
            ("Enable / Disable",
             "Toggle the 'RSI Guard' checkbox on each slot.  Recommended ON "
             "for all EMA crossover and breakout slots.  Can be combined with "
             "ADX, volume, MTF, and all other filters."),
        ],
    },
    # ── Telegram Alerts ─────────────────────────────────────────
    {
        "title": "Telegram Alerts",
        "intro": (
            "Get instant push notifications on your phone for every trade event.  "
            "Messages include symbol, entry/exit price, SL/TP levels, P&L, "
            "and the strategy reason."
        ),
        "items": [
            ("Setup — Create a Bot",
             "1. Open Telegram and search for @BotFather.\n"
             "2. Send /newbot and follow the prompts to name your bot.\n"
             "3. Copy the bot token (looks like 123456:ABC-DEF...) into Settings → Bot Token."),
            ("Setup — Get Your Chat ID",
             "1. Search for @userinfobot on Telegram and press Start.\n"
             "2. It replies with your Chat ID (a number like 123456789).\n"
             "3. Paste it into Settings → Chat ID.\n\n"
             "For group alerts, add the bot to a group and use the group's chat ID "
             "(will be a negative number)."),
            ("What Gets Sent",
             "  📈/📉  Position opened  — symbol, side, entry price, size, leverage, SL/TP levels\n"
             "  ✅/🔴  Position closed  — symbol, entry/exit, % change, P&L, reason\n"
             "  🔄  Trailing SL updated — old → new SL price\n\n"
             "Messages are sent asynchronously so they never slow down the bot loop."),
            ("Test Button",
             "Click 'Send Test Message' in Settings to verify your token and chat ID "
             "are correct.  You should receive a test message within 2 seconds."),
            ("Telegram Commands (overview)",
             "When the bot is running with Telegram enabled, a command listener "
             "automatically starts polling for messages you send to the bot.  "
             "This lets you monitor and control the bot entirely from your phone."),
        ],
    },
    # ── Telegram Commands ───────────────────────────────────────
    {
        "title": "Telegram Commands (Phone Control)",
        "intro": (
            "Send commands to your Telegram bot to check status, manage "
            "positions, and start/stop the bot — all from your phone.  "
            "The command listener uses long-polling and checks for new "
            "messages every few seconds with near-zero latency."
        ),
        "items": [
            ("/status",
             "Shows a full dashboard summary:\n"
             "  • Whether the bot is running or stopped\n"
             "  • Account balance (perps + spot combined)\n"
             "  • Session P&L and total trade count\n"
             "  • Every open position with symbol, side, entry price,\n"
             "    current price, and unrealised % change\n\n"
             "Positions are colour-coded 🟢 green (profit) or 🔴 red (loss)."),
            ("/stop",
             "Gracefully stops the bot.  The trading loop ends, the news "
             "monitor shuts down, and the UI updates to 'Stopped'.  "
             "Open positions are NOT closed — they remain on-chain with "
             "their SL/TP trigger orders intact.  Use /close all first "
             "if you want to flatten before stopping."),
            ("/start",
             "Starts the bot remotely.  It re-reads your saved slot "
             "configurations, initialises exchange clients, sets leverage, "
             "and begins the trading loop — exactly like pressing the Start "
             "button in the GUI.  If the bot is already running it replies "
             "with a notice and does nothing."),
            ("/close BTC  (or any symbol)",
             "Closes the position for a specific symbol.  The bot:\n"
             "  1. Finds the matching slot (matches BTC, ETH, SOL, HYPE, etc.)\n"
             "  2. Cancels any outstanding SL/TP trigger orders for that symbol\n"
             "  3. Sends a market-close order to flatten the position\n"
             "  4. Sends a Telegram close notification with P&L\n"
             "  5. Resets the slot so it can open a new position next cycle\n\n"
             "The symbol name is case-insensitive (btc, Btc, BTC all work)."),
            ("/close all",
             "Closes every open position across all slots.  Each slot's "
             "SL/TP orders are cancelled first, then a market-close is sent.  "
             "Same as clicking 'Close Position' in the GUI."),
            ("/slots",
             "Lists all active slot configurations:\n"
             "  • Symbol and trading interval\n"
             "  • Strategy name and custom parameters\n"
             "  • Position size ($) and leverage\n"
             "  • SL% and TP% levels\n"
             "  • Whether Trailing SL and MTF are enabled\n"
             "  • Current position status (LONG / SHORT / none)"),
            ("/help",
             "Replies with a quick-reference list of all available commands."),
            ("How It Works",
             "The listener uses the Telegram Bot API's getUpdates endpoint "
             "with long-polling (15-second timeout per request).  When you "
             "start the bot, it flushes any old messages so stale commands "
             "from before startup are never replayed.\n\n"
             "Commands run on a background thread.  Any command that modifies "
             "the UI (start, stop, close) is dispatched to the main thread "
             "via tkinter's after() method for thread safety."),
            ("Security",
             "Only messages from your configured Chat ID are processed.  "
             "Commands from any other user or group are silently ignored "
             "and logged as 'unauthorised'.  Your bot token and chat ID "
             "are stored in your local .env file and never transmitted "
             "anywhere except to the Telegram API."),
        ],
    },
    # ── HYPE Trading ────────────────────────────────────────────
    {
        "title": "HYPE Trading Pair",
        "intro": (
            "HYPE (the Hyperliquid native token) is available as a perpetual "
            "futures contract on the platform."
        ),
        "items": [
            ("How to trade HYPE",
             "Select HYPE from the Symbol dropdown in any slot.  It trades on "
             "the native perps DEX (no cash: prefix needed) just like BTC, ETH, and SOL.\n"
             "All strategies, SL/TP, trailing SL, and multi-TF confirmation work "
             "with HYPE the same as any other asset."),
        ],
    },
    # ── TradeXYZ DEX ────────────────────────────────────────────
    {
        "title": "TradeXYZ (xyz:) Pairs",
        "intro": (
            "TradeXYZ is a HIP-3 builder-deployed perp DEX on Hyperliquid offering "
            "stocks, commodities, indices, and forex pairs."
        ),
        "items": [
            ("How to trade xyz pairs",
             "Select any xyz: prefixed symbol from the Symbol dropdown (e.g. xyz:TSLA, "
             "xyz:SP500, xyz:GOLD).  Each xyz pair uses isolated margin and supports "
             "up to the per-asset max leverage shown on the exchange.\n"
             "All strategies, SL/TP, trailing SL, and multi-TF confirmation work "
             "with xyz pairs the same as native perps or cash pairs."),
            ("Available categories",
             "Stocks: xyz:TSLA, xyz:NVDA, xyz:AAPL, xyz:MSFT, xyz:GOOGL, xyz:AMZN, "
             "xyz:META, xyz:AMD, xyz:PLTR, xyz:COIN, xyz:HOOD, xyz:MSTR, xyz:NFLX, etc.\n"
             "Commodities: xyz:GOLD, xyz:SILVER, xyz:CL, xyz:COPPER, xyz:NATGAS, "
             "xyz:PLATINUM, xyz:PALLADIUM, xyz:BRENTOIL\n"
             "Indices: xyz:SP500, xyz:JP225, xyz:KR200, xyz:XYZ100\n"
             "Forex: xyz:JPY, xyz:EUR\n"
             "ETFs: xyz:EWY, xyz:EWJ, xyz:URNM"),
        ],
    },
    # ── News Monitor ────────────────────────────────────────────
    {
        "title": "News Monitor",
        "intro": "",
        "items": [
            ("How it works",
             "The bot polls RSS feeds and CryptoPanic for breaking news, scores "
             "headlines by keyword relevance, and classifies them by impact:\n"
             "  • CRITICAL  →  auto-closes all positions if bearish\n"
             "  • HIGH         →  tightens risk, logged prominently\n"
             "  • MEDIUM     →  sentiment bias blocks opposing entries\n"
             "  • LOW          →  informational only"),
            ("Sentiment Override",
             "If recent high-impact news is bearish the bot will block new LONG "
             "entries (and vice-versa for bullish news).  This prevents opening "
             "trades against strong macro momentum."),
        ],
    },
    # ── Predictions Tab ─────────────────────────────────────────
    {
        "title": "Predictions Tab — HIP-4 Outcome Markets",
        "intro": (
            "The Predictions tab trades HIP-4 prediction markets — binary outcome "
            "tokens that pay $1 if an event happens (e.g. 'BTC above $100K by June') "
            "and $0 otherwise.  The bot uses Black-Scholes digital option pricing to "
            "detect mispriced outcomes and trade the edge."
        ),
        "items": [
            ("How it works",
             "Each prediction market has YES and NO tokens priced 0–1.\n"
             "The bot calculates a theoretical fair value using the Black-Scholes "
             "binary option model (based on current underlying price, strike, time to "
             "expiry, and volatility).\n\n"
             "  edge = theoretical value − market price\n\n"
             "Positive edge → market is cheap → BUY.\n"
             "Negative edge → market is rich → SELL.\n\n"
             "Positions auto-close when edge converges, flips sign, hits stop-loss, "
             "or expiry approaches."),
            ("Scan",
             "Click 🔍 Scan (or enable Auto-Scan) to fetch all live prediction "
             "markets, price them, and display opportunities in the Outcomes table.\n"
             "Each row shows the coin, underlying asset, expiry, strike price, "
             "theoretical value, market price, edge, implied vol, and trade signal."),
            ("Auto-Scan (60s)",
             "When checked, the bot automatically re-scans every 60 seconds.  "
             "Combined with Auto-Execute, this creates a fully autonomous "
             "prediction-market trading loop."),
        ],
    },
    {
        "title": "Predictions — Auto-Execute & Selectiveness Controls",
        "intro": (
            "The controls bar below the scan buttons lets you fine-tune which "
            "signals get auto-executed and how aggressively the bot trades."
        ),
        "items": [
            ("⚡ Auto-Execute",
             "Master switch for automatic trade execution.  When OFF, the bot "
             "only scans and displays opportunities — no orders are placed.\n"
             "When ON, qualifying signals are immediately sent to the exchange "
             "after each scan.  Both Auto-Scan and Auto-Execute must be ON for "
             "fully autonomous trading."),
            ("Min Strength  (default 0.30)",
             "Only auto-execute signals with strength ≥ this threshold.\n"
             "Strength is calculated as:  strength = |edge| / 0.10\n"
             "  • 0.10 → executes almost everything (any edge ≥ 1¢)\n"
             "  • 0.30 → requires ≥ 3¢ edge (moderate selectiveness)\n"
             "  • 0.60 → requires ≥ 6¢ edge (conservative)\n"
             "  • 1.00 → requires ≥ 10¢ edge (very selective)\n\n"
             "This is your primary selectiveness dial — higher = fewer, "
             "higher-conviction trades."),
            ("Min Edge  (default 0.03)",
             "Minimum |edge| required to generate a signal at all.  Signals "
             "below this threshold are not even shown as opportunities.\n"
             "Works together with Min Strength: Min Edge filters at scan time, "
             "Min Strength filters at execution time."),
            ("Kelly %  (default 0.25)",
             "Fraction of the Kelly criterion used for position sizing.\n"
             "Kelly optimal = edge / (1 − fair_value), then multiplied by this fraction.\n"
             "  • 0.10 → very conservative (10% of Kelly)\n"
             "  • 0.25 → quarter Kelly (recommended)\n"
             "  • 0.50 → half Kelly (aggressive)\n"
             "  • 1.00 → full Kelly (maximum growth, maximum drawdown)\n\n"
             "Higher values = larger position sizes per trade."),
            ("Max Pos  (default 5)",
             "Maximum number of concurrent prediction positions.  Once this "
             "many positions are open, new BUY/SELL signals are ignored until "
             "an existing position closes.\n"
             "Lower = more concentrated bets.  Higher = more diversified."),
            ("Max Exposure  (default 100)",
             "Total USDC across all open prediction positions.  Acts as a "
             "portfolio-level risk cap.  If adding a new trade would exceed "
             "this limit, the size is reduced or the trade is skipped."),
            ("IOC (market)",
             "When checked, orders use Immediate-Or-Cancel (IOC) — fills "
             "instantly at available prices like a market order.\n"
             "When unchecked (default), orders use Good-Til-Cancelled (GTC) "
             "limit orders at the calculated edge price.  GTC gives better "
             "fills but may not execute immediately."),
            ("Vol Override  (default: auto)",
             "Override the annualised volatility used in the Black-Scholes model.\n"
             "  • 'auto' → uses historical vol from the underlying asset\n"
             "  • 0.50 → fixed 50% vol (lower vol = tighter theo values)\n"
             "  • 1.20 → fixed 120% vol (higher vol = wider theo values)\n\n"
             "Useful for testing or when you believe the market's implied vol "
             "is wrong."),
        ],
    },
    {
        "title": "Predictions — Positions & Risk Management",
        "intro": (
            "How the bot manages open prediction positions and protects capital."
        ),
        "items": [
            ("Position Tracking",
             "Every trade is tracked in the Arb Positions table showing coin, "
             "YES/NO side, direction (BUY/SELL), size, entry price, current "
             "price, entry edge, and unrealised P&L."),
            ("Auto-Close: Edge Converged",
             "When the edge on an open position shrinks below 0.5¢ (close_edge), "
             "the bot automatically closes it — the mispricing has been corrected "
             "and there's no reason to hold."),
            ("Auto-Close: Edge Flipped",
             "If the edge reverses (you bought cheap but now it's rich), "
             "the bot closes to avoid giving back profit."),
            ("Auto-Close: Stop Loss",
             "If unrealised loss exceeds 10% of position value, the bot "
             "closes to limit damage.  Configurable via max_loss_per_trade "
             "in the strategy defaults."),
            ("Auto-Close: Expiry Imminent",
             "Positions are closed when < 2 minutes remain before expiry "
             "to avoid settlement risk and illiquid end-of-life pricing."),
            ("Close Selected (button)",
             "Select a row in the Positions table and click 'Close Selected' "
             "to manually close any position at the current market price."),
            ("Activity Log",
             "Every scan, trade, close, and alert is logged in the Arb Activity "
             "panel at the bottom of the tab with colour-coded tags:\n"
             "  🟢 BUY   🔴 SELL   🟡 CLOSE   🔵 INFO   ⚠️ WARN"),
        ],
    },
    {
        "title": "Predictions — Funding Your Testnet Account",
        "intro": (
            "Prediction markets trade on the same USDC balance as perps.  "
            "On testnet, you need to deposit mock USDC through the web bridge."
        ),
        "items": [
            ("Step 1: Get Sepolia ETH (gas)",
             "Visit https://www.alchemy.com/faucets/arbitrum-sepolia or "
             "https://faucet.quicknode.com/arbitrum/sepolia to get free "
             "Arbitrum Sepolia ETH for transaction gas."),
            ("Step 2: Get testnet USDC",
             "Visit https://faucet.circle.com/ and select 'Arbitrum Sepolia' "
             "to mint testnet USDC to your wallet."),
            ("Step 3: Deposit into Hyperliquid",
             "Open https://app.hyperliquid-testnet.xyz, connect your wallet, "
             "and click 'Deposit' to bridge USDC into your trading account.\n\n"
             "If the testnet web UI won't load, try Edge/Brave browser, "
             "incognito mode, or disable extensions."),
            ("Check balance from terminal",
             "Run:  py scripts/testnet_faucet.py\n"
             "This shows your current testnet balance and opens the deposit "
             "page if your account is empty."),
            ("No balance needed for scanning",
             "The Predictions tab can scan and detect opportunities with $0 "
             "balance.  Only auto-execute requires funded USDC.  Orders will "
             "simply fail to fill until your account is funded."),
        ],
    },
]


class HelpTab(tk.Frame):
    """Scrollable reference guide for all bot settings."""

    def __init__(self, parent, **kw):
        super().__init__(parent, bg=BG_DARK, **kw)

        # ── Scrollable canvas ───────────────────────────────────
        canvas = tk.Canvas(self, bg=BG_DARK, highlightthickness=0)
        scrollbar = tk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self._inner = tk.Frame(canvas, bg=BG_DARK)
        self._inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=self._inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        self._build_content()

    # ── Build all sections ──────────────────────────────────────
    def _build_content(self):
        p = self._inner

        # Page title
        tk.Label(
            p, text="Settings & Strategy Reference",
            font=FONT_TITLE, bg=BG_DARK, fg=TEXT, anchor="w",
        ).pack(fill="x", padx=PAD_X, pady=(PAD_Y, 4))

        tk.Label(
            p,
            text="A quick reference for every configurable parameter in the bot.",
            font=FONT_SMALL, bg=BG_DARK, fg=TEXT_DIM, anchor="w",
        ).pack(fill="x", padx=PAD_X, pady=(0, PAD_Y))

        for section in _SECTIONS:
            self._add_section(p, section)

    def _add_section(self, parent, section: dict):
        card = Card(parent, title=section["title"])
        card.pack(fill="x", padx=PAD_X, pady=PAD_Y)

        if section.get("intro"):
            tk.Label(
                card, text=section["intro"],
                font=FONT_BODY, bg=BG_CARD, fg=TEXT, anchor="w",
                wraplength=700, justify="left",
            ).pack(fill="x", padx=CARD_PAD, pady=(0, 8))

        for name, description in section["items"]:
            # Parameter name
            tk.Label(
                card, text=name,
                font=(FONT_FAMILY, 11, "bold"), bg=BG_CARD, fg=ACCENT,
                anchor="w",
            ).pack(fill="x", padx=CARD_PAD, pady=(6, 0))

            # Description
            tk.Label(
                card, text=description,
                font=FONT_BODY, bg=BG_CARD, fg=TEXT_DIM, anchor="w",
                wraplength=680, justify="left",
            ).pack(fill="x", padx=(CARD_PAD + 12, CARD_PAD), pady=(0, 4))

        # Bottom padding inside card
        tk.Frame(card, bg=BG_CARD, height=6).pack()
