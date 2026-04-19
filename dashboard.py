"""
Hyperliquid Trading Bot – Desktop Dashboard
============================================
Main entrypoint that assembles the GUI, connects to the trading engine,
and runs everything.

  Usage:   py dashboard.py
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import Config
from core.exchange import HyperliquidClient
from core.market_data import MarketData
from core.risk_manager import RiskManager
from core.news_monitor import NewsMonitor, Impact, NewsItem
from core.email_notifier import EmailNotifier
from core.telegram_notifier import TelegramNotifier, TelegramCommandListener
from strategies.factory import get_strategy
from strategies.base import SignalType

from gui.theme import *
from gui.sidebar import Sidebar
from gui.dashboard_tab import DashboardTab
from gui.log_tab import TradeLogTab
from gui.news_tab import NewsTab
from gui.settings_tab import SettingsTab
from gui.help_tab import HelpTab
from gui.predictions_tab import PredictionsTab

# ── Logging setup ───────────────────────────────────────────────
_log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(_log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(_log_dir, "bot.log"), encoding="utf-8"),
    ],
)
logger = logging.getLogger("dashboard")


# ════════════════════════════════════════════════════════════════
#  Application
# ════════════════════════════════════════════════════════════════
class DashboardApp:
    """Main application orchestrating GUI ↔ bot engine."""

    TITLE = "Hyperliquid Trading Bot"
    MIN_W, MIN_H = 1280, 780

    def __init__(self):
        # ── Root window ─────────────────────────────────────────
        self.root = tk.Tk()
        self.root.title(self.TITLE)
        self.root.configure(bg=BG_DARK)
        self.root.minsize(self.MIN_W, self.MIN_H)
        self.root.geometry("1440x860")

        # Icon (skip if missing)
        try:
            ico = Path(__file__).parent / "icon.ico"
            if ico.exists():
                self.root.iconbitmap(str(ico))
        except Exception:
            pass

        # ── State ───────────────────────────────────────────────
        self._bot_running = False
        self._bot_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._client: Optional[HyperliquidClient] = None
        self._market_data: Optional[MarketData] = None
        self._clients: dict[str, HyperliquidClient] = {}
        self._data_sources: dict[str, MarketData] = {}
        self._risk_mgr: Optional[RiskManager] = None
        self._strategy = None
        self._news_monitor: Optional[NewsMonitor] = None
        self._outcome_monitor = None      # OutcomeMonitor instance
        self._arb_strategy = None          # OutcomeArbStrategy instance
        self._outcome_client = None        # OutcomeClient instance
        self._pricing_model = None         # PriceBinaryModel instance
        self._auto_scan_active = False
        self._auto_exec_active = False     # auto-execute trades on scan
        self._prediction_exchange = None   # SDK Exchange for outcome tokens
        self._email: Optional[EmailNotifier] = None
        self._telegram: Optional[TelegramNotifier] = None
        self._tg_listener: Optional[TelegramCommandListener] = None

        # Session stats
        self._daily_pnl = 0.0
        self._total_trades = 0
        self._wins = 0
        self._last_signal = "--"
        self._prev_price: Optional[float] = None

        # Per-slot state:  slot_id -> {entry, type, strategy, risk_mgr, ...}
        self._slot_state: dict[int, dict] = {}
        # Legacy single-position tracking (for chart overlay)
        self._position_entry: Optional[float] = None
        self._position_type: Optional[str] = None

        # ── Layout: sidebar | notebook ──────────────────────────
        self.sidebar = Sidebar(self.root)
        self.sidebar.pack(side="left", fill="y")

        right = tk.Frame(self.root, bg=BG_DARK)
        right.pack(side="left", fill="both", expand=True)

        # ttk Notebook style – Hyperliquid-inspired flat tabs
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Dark.TNotebook", background=BG_DARK,
                         borderwidth=0, tabmargins=[0, 0, 0, 0])
        style.configure("Dark.TNotebook.Tab",
                         background=BG_DARK, foreground=TEXT_DIM,
                         padding=[18, 10], font=(FONT_FAMILY, 10, "bold"),
                         borderwidth=0)
        style.map("Dark.TNotebook.Tab",
                  background=[("selected", BG_DARK)],
                  foreground=[("selected", ACCENT)])

        # Combobox style – dark theme
        style.configure("TCombobox",
                         fieldbackground=BG_INPUT, background=BG_INPUT,
                         foreground=TEXT, borderwidth=1,
                         arrowcolor=TEXT_DIM)
        style.map("TCombobox",
                  fieldbackground=[("readonly", BG_INPUT)],
                  foreground=[("readonly", TEXT)],
                  selectbackground=[("readonly", BG_INPUT)],
                  selectforeground=[("readonly", TEXT)])

        self.notebook = ttk.Notebook(right, style="Dark.TNotebook")
        self.notebook.pack(fill="both", expand=True, padx=(0, 4), pady=4)

        # ── Tabs ────────────────────────────────────────────────
        self.dashboard_tab = DashboardTab(
            self.notebook,
            on_start=self._on_start,
            on_stop=self._on_stop,
            on_close_position=self._on_close_position,
        )
        self.notebook.add(self.dashboard_tab, text="  📊 Dashboard  ")

        self.news_tab = NewsTab(
            self.notebook,
            on_refresh=self._manual_news_refresh,
        )
        self.notebook.add(self.news_tab, text="  📰 News & Events  ")

        self.log_tab = TradeLogTab(self.notebook)
        self.notebook.add(self.log_tab, text="  📝 Trade Log  ")

        self.settings_tab = SettingsTab(
            self.notebook,
            on_save=self._on_save_settings,
        )
        self.notebook.add(self.settings_tab, text="  ⚙ Settings  ")

        self.predictions_tab = PredictionsTab(
            self.notebook,
            on_scan=self._on_prediction_scan,
            on_execute=self._on_prediction_execute,
            on_close_position=self._on_prediction_close,
            on_toggle_auto=self._on_prediction_auto_toggle,
            on_toggle_auto_exec=self._on_prediction_auto_exec_toggle,
        )
        self.notebook.add(self.predictions_tab, text="  🎯 Predictions  ")

        self.help_tab = HelpTab(self.notebook)
        self.notebook.add(self.help_tab, text="  ❓ Help  ")

        # ── Load current .env into settings ─────────────────────
        self._load_env_to_settings()

        # ── Wire sidebar transfer button ────────────────────────
        self.sidebar.set_transfer_callback(self._on_transfer_spot_to_perps)

        # ── Periodic UI updates ─────────────────────────────────
        self._schedule_ui_updates()

        # ── Window close ────────────────────────────────────────
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._log("Dashboard initialized. Configure settings and press Start.", "info")

    # ════════════════════════════════════════════════════════════
    #  Settings load / save
    # ════════════════════════════════════════════════════════════
    def _load_env_to_settings(self):
        """Load current Config values into the Settings tab."""
        Config._parse_slots()
        cfg = {
            "PRIVATE_KEY": Config.PRIVATE_KEY,
            "WALLET_ADDRESS": Config.WALLET_ADDRESS,
            "USE_TESTNET": Config.USE_TESTNET,
            "POSITION_SIZE_USD": Config.POSITION_SIZE_USD,
            "LOOP_INTERVAL_SEC": Config.LOOP_INTERVAL_SEC,
            "MAX_DAILY_LOSS_USD": Config.MAX_DAILY_LOSS_USD,
            "SLOTS": Config.POSITION_SLOTS,
            "EMAIL_ENABLED": Config.EMAIL_ENABLED,
            "SMTP_SERVER": Config.SMTP_SERVER,
            "SMTP_PORT": Config.SMTP_PORT,
            "EMAIL_SENDER": Config.EMAIL_SENDER,
            "EMAIL_PASSWORD": Config.EMAIL_PASSWORD,
            "EMAIL_RECIPIENT": Config.EMAIL_RECIPIENT,
            "TELEGRAM_ENABLED": Config.TELEGRAM_ENABLED,
            "TELEGRAM_BOT_TOKEN": Config.TELEGRAM_BOT_TOKEN,
            "TELEGRAM_CHAT_ID": Config.TELEGRAM_CHAT_ID,
        }
        self.settings_tab.load_config(cfg)

    def _on_save_settings(self, cfg: dict):
        """Apply settings and write to .env file."""
        # Update runtime Config
        Config.PRIVATE_KEY = cfg.get("PRIVATE_KEY", "")
        Config.WALLET_ADDRESS = cfg.get("WALLET_ADDRESS", "")
        Config.USE_TESTNET = cfg.get("USE_TESTNET", True)
        Config.LOOP_INTERVAL_SEC = int(cfg.get("LOOP_INTERVAL_SEC", 15))
        Config.MAX_DAILY_LOSS_USD = float(cfg.get("MAX_DAILY_LOSS_USD", 500))

        # Email
        Config.EMAIL_ENABLED = cfg.get("EMAIL_ENABLED", False)
        Config.SMTP_SERVER = cfg.get("SMTP_SERVER", "smtp.gmail.com")
        Config.SMTP_PORT = int(cfg.get("SMTP_PORT", 587))
        Config.EMAIL_SENDER = cfg.get("EMAIL_SENDER", "")
        Config.EMAIL_PASSWORD = cfg.get("EMAIL_PASSWORD", "")
        Config.EMAIL_RECIPIENT = cfg.get("EMAIL_RECIPIENT", "")

        # Telegram
        Config.TELEGRAM_ENABLED = cfg.get("TELEGRAM_ENABLED", False)
        Config.TELEGRAM_BOT_TOKEN = cfg.get("TELEGRAM_BOT_TOKEN", "")
        Config.TELEGRAM_CHAT_ID = cfg.get("TELEGRAM_CHAT_ID", "")

        # Slots
        slots = cfg.get("SLOTS", [])
        Config.POSITION_SLOTS = slots

        # Derive legacy single-symbol fields from first active slot
        active = Config.get_active_slots()
        if active:
            first = active[0]
            Config.SYMBOL = first['symbol']
            Config.CANDLE_INTERVAL = first['interval']
            Config.STRATEGY = first['strategy']
            Config.STOP_LOSS_PCT = first['sl']
            Config.TAKE_PROFIT_PCT = first['tp']
            Config.MAX_LEVERAGE = first['leverage']
            Config.MAX_OPEN_POSITIONS = len(active)

        # Persist to .env
        try:
            env_path = Path(__file__).parent / ".env"
            lines = [
                f"PRIVATE_KEY={Config.PRIVATE_KEY}",
                f"WALLET_ADDRESS={Config.WALLET_ADDRESS}",
                f"USE_TESTNET={'true' if Config.USE_TESTNET else 'false'}",
                f"SYMBOL={Config.SYMBOL}",
                f"MAX_LEVERAGE={Config.MAX_LEVERAGE}",
                f"STRATEGY={Config.STRATEGY}",
                f"CANDLE_INTERVAL={Config.CANDLE_INTERVAL}",
                f"LOOP_INTERVAL_SEC={Config.LOOP_INTERVAL_SEC}",
                f"STOP_LOSS_PCT={Config.STOP_LOSS_PCT}",
                f"TAKE_PROFIT_PCT={Config.TAKE_PROFIT_PCT}",
                f"MAX_OPEN_POSITIONS={Config.MAX_OPEN_POSITIONS}",
                f"MAX_DAILY_LOSS_USD={Config.MAX_DAILY_LOSS_USD}",
                f"EMAIL_ENABLED={'true' if Config.EMAIL_ENABLED else 'false'}",
                f"SMTP_SERVER={Config.SMTP_SERVER}",
                f"SMTP_PORT={Config.SMTP_PORT}",
                f"EMAIL_SENDER={Config.EMAIL_SENDER}",
                f"EMAIL_PASSWORD={Config.EMAIL_PASSWORD}",
                f"EMAIL_RECIPIENT={Config.EMAIL_RECIPIENT}",
                f"TELEGRAM_ENABLED={'true' if Config.TELEGRAM_ENABLED else 'false'}",
                f"TELEGRAM_BOT_TOKEN={Config.TELEGRAM_BOT_TOKEN}",
                f"TELEGRAM_CHAT_ID={Config.TELEGRAM_CHAT_ID}",
            ]
            for s in slots:
                slot_env = Config.slot_to_env(s)
                lines.append(f"SLOT_{s['slot']}={slot_env}")
                # Sync process environment so _parse_slots() reads fresh data
                os.environ[f"SLOT_{s['slot']}"] = slot_env
            # Clear any leftover slot env vars beyond the current set
            for i in range(len(slots) + 1, Config.MAX_SLOTS + 1):
                os.environ.pop(f"SLOT_{i}", None)
            env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            self._log("Settings saved to .env", "info")
            if self._bot_running:
                self._log("⚠ Bot is running — restart to apply new settings", "warn")
        except Exception as e:
            self._log(f"Failed to save .env: {e}", "error")
            messagebox.showerror("Save Error", str(e))

    # ════════════════════════════════════════════════════════════
    #  Bot control
    # ════════════════════════════════════════════════════════════
    def _on_start(self):
        """Start the trading bot in a background thread."""
        if self._bot_running:
            return

        # Always apply current UI settings before starting
        self._on_save_settings(self.settings_tab.get_config())

        self._log("Starting bot...", "info")
        self._stop_event.clear()

        try:
            # Validate
            Config.validate()

            # Check active slots
            active_slots = Config.get_active_slots()
            if not active_slots:
                # Fallback to legacy single-symbol mode
                active_slots = [{
                    'slot': 0,
                    'symbol': Config.SYMBOL,
                    'interval': Config.CANDLE_INTERVAL,
                    'strategy': Config.STRATEGY,
                    'sl': Config.STOP_LOSS_PCT,
                    'tp': Config.TAKE_PROFIT_PCT,
                    'leverage': Config.MAX_LEVERAGE,
                    'enabled': True,
                    'size_usd': Config.POSITION_SIZE_USD,
                    'strategy_params': {},
                }]

            # Determine which DEX modes are needed
            needed_dexes: set[str] = set()
            for s in active_slots:
                needed_dexes.add(Config.dex_for_symbol(s['symbol']))
            has_native = "" in needed_dexes
            Config.DEX = "" if has_native else next(iter(sorted(needed_dexes)), "")

            # Initialise exchange clients – one per DEX mode
            self._clients: dict[str, HyperliquidClient] = {}
            self._data_sources: dict[str, MarketData] = {}
            for dex_key in sorted(needed_dexes):
                self._clients[dex_key] = HyperliquidClient(
                    private_key=Config.PRIVATE_KEY,
                    wallet_address=Config.WALLET_ADDRESS,
                    testnet=Config.USE_TESTNET,
                    dex=dex_key,
                )
                self._data_sources[dex_key] = MarketData(
                    testnet=Config.USE_TESTNET, dex=dex_key)

            # Backward-compat: keep self._client pointing at the first DEX
            first_dex = "" if has_native else sorted(needed_dexes)[0]
            self._client = self._clients[first_dex]
            self._market_data = self._data_sources[first_dex]

            # Initialise email notifier
            self._email = EmailNotifier(
                smtp_server=Config.SMTP_SERVER,
                smtp_port=Config.SMTP_PORT,
                sender_email=Config.EMAIL_SENDER,
                sender_password=Config.EMAIL_PASSWORD,
                recipient_email=Config.EMAIL_RECIPIENT or Config.EMAIL_SENDER,
                enabled=Config.EMAIL_ENABLED,
            )

            # Initialise Telegram notifier
            self._telegram = TelegramNotifier(
                bot_token=Config.TELEGRAM_BOT_TOKEN,
                chat_id=Config.TELEGRAM_CHAT_ID,
                enabled=Config.TELEGRAM_ENABLED,
            )

            # Initialise Telegram command listener
            if Config.TELEGRAM_ENABLED and Config.TELEGRAM_BOT_TOKEN and Config.TELEGRAM_CHAT_ID:
                self._tg_listener = TelegramCommandListener(
                    bot_token=Config.TELEGRAM_BOT_TOKEN,
                    chat_id=Config.TELEGRAM_CHAT_ID,
                    notifier=self._telegram,
                )
                self._tg_listener.on_status = self._tg_cmd_status
                self._tg_listener.on_stop = self._tg_cmd_stop
                self._tg_listener.on_start = self._tg_cmd_start
                self._tg_listener.on_close = self._tg_cmd_close
                self._tg_listener.on_slots = self._tg_cmd_slots
                self._tg_listener.start()

            # Set up per-slot state
            self._slot_state = {}
            for slot in active_slots:
                sid = slot['slot']
                symbol = slot['symbol']

                # Set leverage (isolated for HIP-3)
                is_cross = not Config.is_hip3_symbol(symbol)
                self._client_for(symbol).update_leverage(
                    symbol, slot['leverage'], is_cross=is_cross)

                self._slot_state[sid] = {
                    'config': slot,
                    'strategy': get_strategy(slot['strategy'],
                                             **slot.get('strategy_params', {})),
                    'risk_mgr': RiskManager(
                        stop_loss_pct=slot['sl'],
                        take_profit_pct=slot['tp'],
                        max_open_positions=1,
                        max_daily_loss_usd=Config.MAX_DAILY_LOSS_USD,
                    ),
                    'position_type': None,
                    'position_entry': None,
                    'last_signal': '--',
                    'last_iteration': 0,
                    # Trailing SL state
                    'trail_high_water': None,
                    'trail_low_water': None,
                    'current_sl_price': None,
                    # Loss cooldown state
                    'consecutive_losses': 0,
                    'cooldown_until': None,  # datetime when cooldown expires
                    # ATR cache (updated each iteration)
                    'last_atr': None,
                    # Per-slot order tracking (same-symbol safety)
                    'sl_oid': None,   # on-chain SL order ID
                    'tp_oid': None,   # on-chain TP order ID
                    'slot_size': 0.0, # coins this slot is responsible for
                }
                sp_str = ""
                sp = slot.get('strategy_params', {})
                if sp:
                    sp_str = " | params: " + ", ".join(f"{k}={v}" for k, v in sp.items())
                size = slot.get('size_usd', 100)
                trail_str = " | TrailSL" if slot.get('trailing_sl') else ""
                mtf_str = " | MTF" if slot.get('mtf_enabled', True) else ""
                regime_str = " | ADX" if slot.get('regime_filter') else ""
                atr_str = " | ATR-SL" if slot.get('atr_stops') else ""
                cd_str = " | Cooldown" if slot.get('loss_cooldown') else ""
                vol_str = " | VolConf" if slot.get('volume_confirm') else ""
                rsi_g_str = " | RSIGuard" if slot.get('rsi_guard') else ""
                self._log(f"Slot #{sid}: {symbol} | {slot['interval']} | "
                          f"{slot['strategy']} | ${size} | "
                          f"SL {slot['sl']}% TP {slot['tp']}% "
                          f"Lev {slot['leverage']}x{sp_str}{trail_str}{mtf_str}"
                          f"{regime_str}{atr_str}{cd_str}{vol_str}{rsi_g_str}", "info")
                # Log strategy internals for debugging
                strat_obj = self._slot_state[sid]['strategy']
                if hasattr(strat_obj, 'overbought'):
                    self._log(f"  └─ RSI thresholds: oversold={strat_obj.oversold}, "
                              f"overbought={strat_obj.overbought}, period={strat_obj.period}", "info")
                elif hasattr(strat_obj, 'fast_period'):
                    self._log(f"  └─ EMA periods: fast={strat_obj.fast_period}, "
                              f"slow={strat_obj.slow_period}", "info")
                elif hasattr(strat_obj, 'lookback_period'):
                    self._log(f"  └─ Breakout: lookback={strat_obj.lookback_period}, "
                              f"threshold={strat_obj.breakout_threshold_pct}%", "info")

            # Warn about duplicate symbols (multi-slot same-symbol)
            symbol_slots: dict[str, list[int]] = {}
            for slot in active_slots:
                symbol_slots.setdefault(slot['symbol'], []).append(slot['slot'])
            for sym, sids in symbol_slots.items():
                if len(sids) > 1:
                    ids_str = ", ".join(f"#{s}" for s in sids)
                    self._log(
                        f"⚠ Multi-slot: {sym} used by slots {ids_str} — "
                        f"per-slot order tracking active", "warn")

            # Also set legacy risk manager from first slot
            first = active_slots[0]
            self._risk_mgr = RiskManager(
                stop_loss_pct=first['sl'],
                take_profit_pct=first['tp'],
                max_open_positions=len(active_slots),
                max_daily_loss_usd=Config.MAX_DAILY_LOSS_USD,
            )
            self._strategy = get_strategy(first['strategy'],
                                          **first.get('strategy_params', {}))

            # Start news monitor
            self._start_news_monitor()

            # Start outcome monitor for prediction markets
            self._start_outcome_monitor()

            # Update UI
            self._bot_running = True
            self.dashboard_tab.set_running(True)
            network = "Testnet" if Config.USE_TESTNET else "Mainnet"
            self.sidebar.update_connection(True, network)
            self.sidebar.update_bot_status(True)
            self.sidebar.update_account(Config.WALLET_ADDRESS, 0)

            # Launch bot loop thread
            self._bot_thread = threading.Thread(target=self._bot_loop, daemon=True, name="bot-loop")
            self._bot_thread.start()

            slot_summary = ", ".join(f"{s['symbol']}({s['interval']})" for s in active_slots)
            self._log(f"Bot started with {len(active_slots)} slot(s): {slot_summary}", "info")
            if Config.EMAIL_ENABLED:
                self._log(f"Email notifications ON → {Config.EMAIL_RECIPIENT or Config.EMAIL_SENDER}", "info")
            if Config.TELEGRAM_ENABLED:
                self._log(f"Telegram alerts ON → chat {Config.TELEGRAM_CHAT_ID}", "info")
            mtf_slots = [s for s in active_slots if s.get('mtf_enabled', True)]
            if mtf_slots:
                mtf_syms = ', '.join(s['symbol'] for s in mtf_slots)
                self._log(f"Multi-timeframe confirmation ON for: {mtf_syms}", "info")

        except Exception as e:
            import traceback as _tb
            logger.error("Start failed:\n" + _tb.format_exc())
            self._log(f"Failed to start: {e}", "error")
            messagebox.showerror("Start Error", str(e))

    # ── Per-symbol DEX routing ──────────────────────────────────
    @staticmethod
    def _dex_for(symbol: str) -> str:
        """Return the DEX key ('cash', 'xyz', or '') for a given symbol."""
        return Config.dex_for_symbol(symbol)

    def _client_for(self, symbol: str) -> "HyperliquidClient":
        """Return the exchange client for the symbol's DEX."""
        dex = self._dex_for(symbol)
        return self._clients.get(dex, self._client)

    def _data_for(self, symbol: str) -> "MarketData":
        """Return the market data source for the symbol's DEX."""
        dex = self._dex_for(symbol)
        return self._data_sources.get(dex, self._market_data)

    def _on_stop(self):
        """Stop the bot gracefully."""
        if not self._bot_running:
            return
        self._log("Stopping bot...", "warn")
        self._stop_event.set()
        self._bot_running = False
        self.dashboard_tab.set_running(False)
        self.dashboard_tab.clear_market_stats()
        self.sidebar.update_bot_status(False)

        # Stop news monitor
        if self._news_monitor:
            self._news_monitor.stop()
            self._news_monitor = None

        # Stop outcome monitor
        if self._outcome_monitor:
            self._outcome_monitor.stop()
            self._outcome_monitor = None
        self._auto_scan_active = False

        # Stop Telegram command listener
        if self._tg_listener:
            self._tg_listener.stop()
            self._tg_listener = None

        self._log("Bot stopped.", "info")

    def _on_close_position(self):
        """Manually close all open positions across all slots."""
        if not self._clients:
            self._log("Not connected – start bot first.", "warn")
            return
        closed_any = False
        closed_symbols = set()  # track already-closed symbols for multi-slot
        for sid, state in list(self._slot_state.items()):
            symbol = state['config']['symbol']
            client = self._client_for(symbol)
            try:
                # Cancel outstanding SL/TP trigger orders first
                self._cancel_sl_tp(sid, symbol)

                # Only close the on-chain position once per symbol
                if symbol not in closed_symbols:
                    result = client.close_position(symbol)
                    if result:
                        closed_symbols.add(symbol)
                else:
                    result = True  # already closed by earlier slot

                if result and state.get('position_type'):
                    self._log(f"Position closed manually on {symbol} (Slot #{sid})", "warn")
                    self._record_trade(symbol, "CLOSE", "Manual close", slot_id=sid)
                    if self._email and state.get('position_entry'):
                        price = client.get_market_price(symbol) or 0
                        self._email.notify_close(
                            symbol=symbol,
                            side=state.get('position_type', 'LONG'),
                            entry_price=state['position_entry'],
                            exit_price=price,
                            reason="Manual close", slot_id=sid,
                        )
                    if self._telegram and state.get('position_entry'):
                        price = client.get_market_price(symbol) or 0
                        self._telegram.notify_close(
                            symbol=symbol,
                            side=state.get('position_type', 'LONG'),
                            entry_price=state['position_entry'],
                            exit_price=price,
                            reason="Manual close", slot_id=sid,
                        )
                    state['position_type'] = None
                    state['position_entry'] = None
                    state['sl_oid'] = None
                    state['tp_oid'] = None
                    state['slot_size'] = 0
                    state['trail_high_water'] = None
                    state['trail_low_water'] = None
                    state['current_sl_price'] = None
                    closed_any = True
            except Exception as e:
                self._log(f"Close position error on {symbol}: {e}", "error")

        if not closed_any:
            # Fallback: try legacy single symbol
            try:
                result = self._client_for(Config.SYMBOL).close_position(Config.SYMBOL)
                if result:
                    self._log(f"Position closed manually on {Config.SYMBOL}", "warn")
                    self._record_trade(Config.SYMBOL, "CLOSE", "Manual close")
                else:
                    self._log("No open positions to close.", "info")
            except Exception as e:
                self._log(f"Close position error: {e}", "error")

    def _on_transfer_spot_to_perps(self):
        """Transfer all USDC from spot to perps margin account."""
        if not self._client and not self._clients:
            try:
                self._client = HyperliquidClient(
                    private_key=Config.PRIVATE_KEY,
                    wallet_address=Config.WALLET_ADDRESS,
                    testnet=Config.USE_TESTNET,
                    dex=Config.DEX,
                )
            except Exception as e:
                self._log(f"Cannot connect: {e}", "error")
                messagebox.showerror("Error", f"Cannot connect: {e}")
                return

        spot_bal = self._client.get_spot_balance()
        if spot_bal <= 0:
            self._log("No USDC in spot wallet to transfer.", "warn")
            messagebox.showinfo("Transfer", "No USDC available in spot wallet.")
            return

        confirm = messagebox.askyesno(
            "Transfer Spot → Perps",
            f"Transfer ${spot_bal:,.2f} USDC from Spot to Perps margin?\n\n"
            "This is required before the bot can trade.",
        )
        if not confirm:
            return

        self._log(f"Transferring ${spot_bal:,.2f} from Spot → Perps...", "info")
        try:
            success = self._client.transfer_spot_to_perps(spot_bal)
            if success:
                self._log(f"✓ Transferred ${spot_bal:,.2f} to perps margin!", "info")
                # Refresh balances
                new_perps = self._client.get_balance()
                new_spot = self._client.get_spot_balance()
                self.sidebar.update_account(Config.WALLET_ADDRESS, new_perps, new_spot)
                messagebox.showinfo("Transfer Complete",
                                    f"${spot_bal:,.2f} transferred to perps margin.\n"
                                    f"Perps balance: ${new_perps:,.2f}")
            else:
                self._log("Transfer failed. Check logs.", "error")
                messagebox.showerror("Transfer Failed", "Transfer failed. Check trade log for details.")
        except Exception as e:
            self._log(f"Transfer error: {e}", "error")
            messagebox.showerror("Transfer Error", str(e))

    # ════════════════════════════════════════════════════════════
    #  News monitor
    # ════════════════════════════════════════════════════════════
    def _start_news_monitor(self):
        """Start the background news aggregator."""
        if self._news_monitor and self._news_monitor.is_running:
            return
        self._news_monitor = NewsMonitor(poll_interval=60)

        # Wire callbacks (thread-safe via root.after)
        def _on_news(item: NewsItem):
            self.root.after(0, self._handle_news_item, item)

        def _on_high(item: NewsItem):
            self.root.after(0, self._handle_high_impact, item)

        def _on_critical(item: NewsItem):
            self.root.after(0, self._handle_critical_event, item)

        self._news_monitor.on_news = _on_news
        self._news_monitor.on_high = _on_high
        self._news_monitor.on_critical = _on_critical
        self._news_monitor.start()
        self._log("News monitor started (polling every 60s)", "info")

    def _handle_news_item(self, item: NewsItem):
        """Process any new news item (runs on main thread)."""
        pub_str = item.published.strftime("%H:%M:%S") if item.published else "now"
        self.news_tab.add_news_item(
            headline=item.headline,
            source=item.source,
            published=pub_str,
            impact=int(item.impact),
            sentiment=item.sentiment,
            url=item.url,
            matched_keywords=item.matched_keywords,
        )
        self._update_news_stats()

    def _handle_high_impact(self, item: NewsItem):
        """HIGH impact event – tighten stops, log prominently."""
        self._log(f"⚠ HIGH IMPACT [{item.source}]: {item.headline}", "warn")
        self.log_tab.log.append(
            datetime.now().strftime("%H:%M:%S"),
            f"⚠ NEWS ALERT [{item.impact.name}] {item.headline}",
            "warn",
        )

    def _handle_critical_event(self, item: NewsItem):
        """
        CRITICAL event – e.g. 'US bombs Iran'.
        Auto-close positions if bearish. Log + alert.
        """
        self._log(f"🔴 CRITICAL [{item.source}]: {item.headline}", "error")
        self.log_tab.log.append(
            datetime.now().strftime("%H:%M:%S"),
            f"🔴 CRITICAL NEWS: {item.headline}",
            "error",
        )

        if item.sentiment == "bearish" and self._clients:
            # Auto-close ALL positions as a protective measure
            for sid, state in list(self._slot_state.items()):
                if state.get('position_type'):
                    symbol = state['config']['symbol']
                    client = self._client_for(symbol)
                    self._log(f"Auto-closing {symbol} (Slot #{sid}) due to critical bearish event!", "error")
                    try:
                        # Cancel SL/TP trigger orders first
                        self._cancel_sl_tp(sid, symbol)
                        client.close_position(symbol)
                        self._record_trade(symbol, "CLOSE",
                                           f"Critical news: {item.headline[:60]}", slot_id=sid)
                        if self._email and state.get('position_entry'):
                            price = client.get_market_price(symbol) or 0
                            self._email.notify_close(
                                symbol=symbol,
                                side=state['position_type'],
                                entry_price=state['position_entry'],
                                exit_price=price,
                                reason=f"CRITICAL NEWS: {item.headline[:60]}",
                                slot_id=sid,
                            )
                        if self._telegram and state.get('position_entry'):
                            price = price if 'price' in dir() else (client.get_market_price(symbol) or 0)
                            self._telegram.notify_close(
                                symbol=symbol,
                                side=state['position_type'],
                                entry_price=state['position_entry'],
                                exit_price=price,
                                reason=f"CRITICAL NEWS: {item.headline[:60]}",
                                slot_id=sid,
                            )
                        state['position_type'] = None
                        state['position_entry'] = None
                        state['trail_high_water'] = None
                        state['trail_low_water'] = None
                        state['current_sl_price'] = None
                    except Exception as e:
                        self._log(f"Emergency close failed for {symbol}: {e}", "error")

    def _manual_news_refresh(self):
        """Force a news poll cycle from the UI."""
        if self._news_monitor and self._news_monitor.is_running:
            threading.Thread(target=self._news_monitor._poll_once, daemon=True).start()
            self._log("Manual news refresh triggered", "info")
        else:
            self._log("News monitor not running. Start the bot first.", "warn")

    def _update_news_stats(self):
        """Recalculate and push news stats to the tab."""
        if not self._news_monitor:
            return
        items = self._news_monitor.get_items(limit=500)
        total = len(items)
        critical = sum(1 for i in items if i.impact >= Impact.CRITICAL)
        high = sum(1 for i in items if i.impact >= Impact.HIGH)
        bearish = sum(1 for i in items if i.sentiment == "bearish" and i.impact >= Impact.MEDIUM)
        bullish = sum(1 for i in items if i.sentiment == "bullish" and i.impact >= Impact.MEDIUM)
        sources = len(set(i.source for i in items))
        self.news_tab.update_stats(total, critical, high, bearish, bullish, sources)
        self.news_tab.update_sentiment(self._news_monitor.get_sentiment_bias())

    # ════════════════════════════════════════════════════════════
    #  Prediction markets (HIP-4 outcome arb)
    # ════════════════════════════════════════════════════════════

    def _ensure_prediction_stack(self):
        """Lazily initialise OutcomeClient, PriceBinaryModel, and ArbStrategy."""
        if self._arb_strategy is not None:
            return
        try:
            from core.outcome_client import OutcomeClient
            from core.pricing_model import PriceBinaryModel
            from strategies.outcome_arb import OutcomeArbStrategy, ArbConfig

            testnet = Config.USE_TESTNET
            self._outcome_client = OutcomeClient(testnet=testnet)
            self._pricing_model = PriceBinaryModel(self._outcome_client)
            self._arb_strategy = OutcomeArbStrategy(
                self._outcome_client,
                self._pricing_model,
                config=ArbConfig(
                    min_edge=self.predictions_tab.min_edge,
                    kelly_fraction=self.predictions_tab.kelly_fraction,
                    max_positions=self.predictions_tab.max_positions,
                    max_total_exposure=self.predictions_tab.max_exposure,
                    use_ioc=self.predictions_tab.use_ioc,
                ),
            )
            self._log("Prediction stack initialised", "info")
        except Exception as e:
            self._log(f"Failed to init prediction stack: {e}", "error")

    def _ensure_prediction_exchange(self):
        """Lazily create an SDK Exchange with outcome tokens injected.

        Returns the raw SDK Exchange object, or None on failure.
        """
        if self._prediction_exchange is not None:
            return self._prediction_exchange
        try:
            self._ensure_prediction_stack()
            if not self._outcome_client:
                return None

            # Create a dedicated HyperliquidClient for prediction trading
            pred_client = HyperliquidClient(
                private_key=Config.PRIVATE_KEY,
                wallet_address=Config.WALLET_ADDRESS,
                testnet=Config.USE_TESTNET,
            )
            # Inject outcome tokens so the SDK knows about #-coins
            self._outcome_client.inject_into_sdk(
                pred_client.info, pred_client.exchange,
            )
            self._prediction_exchange = pred_client.exchange
            self._log("Prediction exchange ready (tokens injected)", "info")
            return self._prediction_exchange
        except Exception as e:
            self._log(f"Failed to init prediction exchange: {e}", "error")
            return None

    def _sync_arb_config_from_ui(self):
        """Push GUI control values into the ArbConfig."""
        if not self._arb_strategy:
            return
        cfg = self._arb_strategy.config
        cfg.min_edge = self.predictions_tab.min_edge
        cfg.kelly_fraction = self.predictions_tab.kelly_fraction
        cfg.max_positions = self.predictions_tab.max_positions
        cfg.max_total_exposure = self.predictions_tab.max_exposure
        cfg.use_ioc = self.predictions_tab.use_ioc

    def _on_prediction_scan(self):
        """Manual scan button pressed in Predictions tab."""
        self._ensure_prediction_stack()
        if not self._arb_strategy:
            self.predictions_tab.set_status("Init failed", RED)
            return
        # Sync all config from UI controls
        self._sync_arb_config_from_ui()
        vol = self.predictions_tab.vol_override
        # Run scan in background to avoid blocking GUI
        threading.Thread(target=self._run_prediction_scan, args=(vol,),
                         daemon=True, name="pred-scan").start()

    def _run_prediction_scan(self, vol=None):
        """Runs the arb scan in a background thread and pushes results to GUI."""
        try:
            analyses = self._pricing_model.analyse_all(
                vol=vol,
                default_vol=self._arb_strategy.config.default_vol,
            )
            signals = self._arb_strategy.scan(vol=vol)
            # Push results to GUI on main thread
            self.root.after(0, self._update_predictions_ui, analyses, signals)
        except Exception as e:
            self.root.after(0, self.predictions_tab.log,
                           f"Scan error: {e}", "warn")
            self.root.after(0, self.predictions_tab.set_status,
                           "Scan failed", RED)

    def _update_predictions_ui(self, analyses, signals):
        """Update Predictions tab with scan results (main thread).

        If auto-execute is enabled, filter signals by min_strength and
        execute them on the real SDK Exchange.
        """
        self.predictions_tab.load_scan_results(analyses, signals)

        actionable = [s for s in signals if s.is_actionable]
        executed_count = 0

        # ── Auto-execute pipeline ───────────────────────────────
        if self._auto_exec_active and actionable:
            min_str = self.predictions_tab.min_strength
            qualified = [s for s in actionable if s.strength >= min_str]

            if qualified:
                exchange = self._ensure_prediction_exchange()
                if exchange is not None:
                    self.predictions_tab.log(
                        f"⚡ Auto-executing {len(qualified)} signal(s) "
                        f"(strength ≥ {min_str:.2f})", "warn")
                    results = self._arb_strategy.execute_all(qualified, exchange)
                    executed_count = len(results)
                    for sig in qualified:
                        tag = "buy" if sig.action == "BUY" else (
                            "sell" if sig.action == "SELL" else "close")
                        self.predictions_tab.log(
                            f"  {sig.action} {sig.size:.0f} {sig.coin}"
                            f"({sig.side_label}) @ {sig.limit_price:.4f}  "
                            f"edge={sig.edge:+.4f} str={sig.strength:.2f}",
                            tag)
                    if executed_count:
                        self.predictions_tab.log(
                            f"✓ {executed_count} order(s) placed", "info")
                else:
                    self.predictions_tab.log(
                        "⚠ Auto-execute ON but exchange unavailable", "warn")
            else:
                self.predictions_tab.log(
                    f"No signals pass strength filter ({min_str:.2f})", "scan")

        # ── Update stats & positions ────────────────────────────
        if self._arb_strategy:
            self.predictions_tab.load_positions(self._arb_strategy.open_positions)
            self.predictions_tab.update_stats(
                outcomes=len(analyses),
                opportunities=len(actionable),
                avg_edge=(sum(abs(s.edge) for s in actionable)
                          / max(1, len(actionable)))
                         if actionable else None,
                positions=self._arb_strategy.position_count,
                exposure=self._arb_strategy.total_exposure,
                pnl=0.0,
            )

        status_parts = [f"Scan done — {len(actionable)} opportunity(s)"]
        if executed_count:
            status_parts.append(f"{executed_count} executed")
        status = ", ".join(status_parts)
        self.predictions_tab.set_status(
            status, GREEN if actionable else TEXT_DIM)
        self.predictions_tab.log(
            f"Scan complete: {len(analyses)} outcomes, {len(actionable)} signals",
            "scan")

    def _on_prediction_execute(self, signal=None):
        """Execute a specific arb signal from the GUI."""
        if signal is None or not self._arb_strategy:
            return
        exchange = self._ensure_prediction_exchange()
        if exchange is None:
            self.predictions_tab.log("Cannot execute — exchange unavailable", "warn")
            return
        self._sync_arb_config_from_ui()
        result = self._arb_strategy.execute(signal, exchange)
        tag = "buy" if signal.action == "BUY" else (
            "sell" if signal.action == "SELL" else "close")
        self.predictions_tab.log(
            f"Executed: {signal.action} {signal.size:.0f} {signal.coin} "
            f"@ {signal.limit_price:.4f}", tag)
        if self._arb_strategy:
            self.predictions_tab.load_positions(self._arb_strategy.open_positions)

    def _on_prediction_close(self, coin: str):
        """Close an arb position from the GUI."""
        if not self._arb_strategy:
            return
        pos = self._arb_strategy.open_positions.get(coin)
        if pos is None:
            self.predictions_tab.log(f"No position for {coin}", "warn")
            return
        exchange = self._ensure_prediction_exchange()
        from strategies.outcome_arb import ArbSignal
        close_signal = ArbSignal(
            outcome_id=pos.outcome_id,
            coin=coin,
            side_label=pos.side_label,
            action="CLOSE",
            edge=0.0,
            theo=0.0,
            market=pos.entry_price,
            strength=0.0,
            size=pos.size,
            limit_price=pos.entry_price,
            reason="Manual close from GUI",
        )
        self._arb_strategy.execute(close_signal, exchange)
        self.predictions_tab.remove_position(coin)
        self.predictions_tab.log(f"Closed position: {coin}", "close")

    def _on_prediction_auto_exec_toggle(self, enabled: bool):
        """Toggle auto-execute for prediction trades."""
        self._auto_exec_active = enabled
        if enabled:
            # Pre-warm the exchange so first trade doesn't delay
            threading.Thread(target=self._ensure_prediction_exchange,
                             daemon=True, name="pred-exch-init").start()
        self._log(f"Prediction auto-execute {'ON' if enabled else 'OFF'}", "info")

    def _on_prediction_auto_toggle(self, enabled: bool):
        """Toggle auto-scan for predictions."""
        self._auto_scan_active = enabled
        if enabled:
            self._schedule_prediction_auto_scan()
        self._log(f"Prediction auto-scan {'ON' if enabled else 'OFF'}", "info")

    def _schedule_prediction_auto_scan(self):
        """Schedule repeating prediction scan every 60s."""
        if not self._auto_scan_active:
            return
        self._on_prediction_scan()
        self.root.after(60_000, self._schedule_prediction_auto_scan)

    def _start_outcome_monitor(self):
        """Start the background outcome monitor (new markets, expiry alerts)."""
        if self._outcome_monitor:
            return
        try:
            from core.outcome_monitor import OutcomeMonitor
            self._ensure_prediction_stack()
            if not self._outcome_client:
                return
            self._outcome_monitor = OutcomeMonitor(
                self._outcome_client, poll_interval=120)

            def _on_new(alert):
                self.root.after(0, self.predictions_tab.log,
                                f"New outcome: {alert.message}", "info")

            def _on_expiry(alert):
                self.root.after(0, self.predictions_tab.log,
                                f"⏰ {alert.message}", "warn")

            def _on_any(alert):
                self.root.after(0, self._log,
                                f"[Predictions] {alert.message}", "info")

            self._outcome_monitor.on_new_outcome = _on_new
            self._outcome_monitor.on_expiry_warning = _on_expiry
            self._outcome_monitor.on_any_alert = _on_any
            self._outcome_monitor.start()
            self._log("Outcome monitor started (polling every 120s)", "info")
        except Exception as e:
            self._log(f"Failed to start outcome monitor: {e}", "error")

    # ════════════════════════════════════════════════════════════
    #  Bot loop (runs in background thread)
    # ════════════════════════════════════════════════════════════
    def _bot_loop(self):
        """Main trading loop – iterates each active slot."""
        while not self._stop_event.is_set():
            try:
                # Update balance + all open positions once per cycle
                if self._client or self._clients:
                    try:
                        balance = self._client.get_balance()
                        self.root.after(0, self.sidebar.update_account,
                                        Config.WALLET_ADDRESS, balance)
                    except Exception:
                        pass

                    # Collect ALL on-chain positions across all DEX clients
                    try:
                        all_positions = []
                        seen = set()  # avoid dupes if same client
                        for dex_key, client in self._clients.items():
                            positions = client.get_positions()
                            for pos in positions:
                                pd_ = pos.get("position", {})
                                sym = pd_.get("coin", "?")
                                sz = float(pd_.get("szi", 0))
                                if sz == 0 or sym in seen:
                                    continue
                                seen.add(sym)
                                all_positions.append({
                                    "symbol": sym,
                                    "type": "LONG" if sz > 0 else "SHORT",
                                    "size": abs(sz),
                                    "entry_price": float(pd_.get("entryPx", 0)),
                                    "unrealized_pnl": float(pd_.get("unrealizedPnl", 0)),
                                })
                        self.root.after(0, self.sidebar.update_positions, all_positions)
                    except Exception:
                        pass

                # Run each slot
                for sid, state in list(self._slot_state.items()):
                    if self._stop_event.is_set():
                        return
                    try:
                        self._slot_iteration(sid, state)
                    except Exception as e:
                        logger.error(f"Slot #{sid} error: {e}", exc_info=True)
                        self.root.after(0, self._log, f"Slot #{sid} error: {e}", "error")

            except Exception as e:
                logger.error(f"Bot loop error: {e}", exc_info=True)
                self.root.after(0, self._log, f"Loop error: {e}", "error")

            # Sleep in 1s increments so stop is responsive
            for _ in range(Config.LOOP_INTERVAL_SEC):
                if self._stop_event.is_set():
                    return
                time.sleep(1)

    def _slot_iteration(self, sid: int, state: dict):
        """Single strategy iteration for one slot."""
        if not self._clients:
            return

        slot_cfg = state['config']
        symbol = slot_cfg['symbol']
        interval = slot_cfg['interval']
        strategy = state['strategy']
        risk_mgr = state['risk_mgr']

        # Per-symbol DEX-routed client + data source
        client = self._client_for(symbol)
        data = self._data_for(symbol)

        # -- On-chain position (for sidebar display) ----------------
        position = None
        try:
            pos = client.get_position(symbol)
            if pos:
                pos_data = pos["position"]
                size = float(pos_data["szi"])
                if size != 0:
                    position = {
                        "size": abs(size),
                        "type": "LONG" if size > 0 else "SHORT",
                        "entry_price": float(pos_data["entryPx"]),
                        "unrealized_pnl": float(pos_data["unrealizedPnl"]),
                    }
        except Exception:
            pass

        # Update sidebar display for first slot (legacy)
        if sid == min(self._slot_state.keys()):
            self._position_type = position["type"] if position else None
            self._position_entry = position["entry_price"] if position else None

        # -- Current price ----------------------------------------
        current_price = client.get_market_price(symbol)
        if not current_price:
            return

        if sid == min(self._slot_state.keys()):
            self.root.after(0, self.dashboard_tab.update_price, current_price, self._prev_price)
            self._prev_price = current_price

        # -- News override ----------------------------------------
        news_override = self._check_news_override()

        # ── Per-slot SL/TP fire detection (multi-slot safe) ─────
        # Check if this slot's SL or TP trigger order was consumed on-chain.
        # If an oid disappeared from open orders → that trigger fired.
        _slot_closed = False
        if state.get('slot_size', 0) > 0 and (state.get('sl_oid') or state.get('tp_oid')):
            open_oids = client.get_open_order_oids(symbol)
            sl_gone = bool(state.get('sl_oid') and state['sl_oid'] not in open_oids)
            tp_gone = bool(state.get('tp_oid') and state['tp_oid'] not in open_oids)

            if sl_gone or tp_gone:
                fired = "SL" if sl_gone else "TP"
                self.root.after(0, self._log,
                    f"[Slot #{sid} {symbol}] {fired} triggered — slot position closed", "info")

                # Cancel the REMAINING order for this slot
                if sl_gone and state.get('tp_oid') and not tp_gone:
                    client.cancel_order_by_id(symbol, state['tp_oid'])
                elif tp_gone and state.get('sl_oid') and not sl_gone:
                    client.cancel_order_by_id(symbol, state['sl_oid'])

                # Track consecutive losses for cooldown
                if sl_gone:
                    state['consecutive_losses'] = state.get('consecutive_losses', 0) + 1
                    self.root.after(0, self._log,
                        f"[Slot #{sid} {symbol}] Consecutive losses: {state['consecutive_losses']}",
                        "warn")
                    if slot_cfg.get('loss_cooldown') and state['consecutive_losses'] >= 3:
                        state['cooldown_until'] = time.time() + 1800
                        self.root.after(0, self._log,
                            f"[Slot #{sid} {symbol}] ⏸ Loss cooldown activated (30 min)", "warn")
                else:
                    state['consecutive_losses'] = 0

                # Notify — use the stored SL/TP price as actual exit,
                # not current_price which may have moved since the fill.
                if self._telegram and state.get('position_entry'):
                    if sl_gone:
                        est_exit = state.get('current_sl_price') or current_price
                    else:
                        # TP fired — estimate exit from entry ± tp%
                        entry_px = state.get('position_entry', 0)
                        tp_pct = slot_cfg.get('tp', 1.0)
                        if state.get('position_type') == 'LONG':
                            est_exit = entry_px * (1 + tp_pct / 100)
                        else:
                            est_exit = entry_px * (1 - tp_pct / 100)

                    reason_detail = f"On-chain {fired} triggered"
                    if sl_gone and state.get('current_sl_price'):
                        reason_detail += f" @ ${state['current_sl_price']:,.2f}"

                    self._telegram.notify_close(
                        symbol=symbol,
                        side=state.get('position_type', 'LONG'),
                        entry_price=state.get('position_entry', 0),
                        exit_price=est_exit,
                        reason=reason_detail,
                        slot_id=sid,
                    )

                # Reset this slot's state
                state['position_type'] = None
                state['position_entry'] = None
                state['sl_oid'] = None
                state['tp_oid'] = None
                state['slot_size'] = 0
                state['trail_high_water'] = None
                state['trail_low_water'] = None
                state['current_sl_price'] = None
                _slot_closed = True

        # Fallback: entire on-chain position gone & slot thought it was active
        # (handles case where oids weren't tracked, e.g., after bot restart)
        if not _slot_closed and state.get('position_entry') and not position:
            self.root.after(0, self._log,
                f"[Slot #{sid} {symbol}] Position closed by on-chain SL/TP", "info")
            entry_px = state['position_entry']
            was_long = state.get('position_type') == 'LONG'
            if current_price:
                pnl_sign = (current_price - entry_px) if was_long else (entry_px - current_price)
                if pnl_sign < 0:
                    state['consecutive_losses'] = state.get('consecutive_losses', 0) + 1
                    self.root.after(0, self._log,
                        f"[Slot #{sid} {symbol}] Consecutive losses: {state['consecutive_losses']}",
                        "warn")
                    if slot_cfg.get('loss_cooldown') and state['consecutive_losses'] >= 3:
                        state['cooldown_until'] = time.time() + 1800
                else:
                    state['consecutive_losses'] = 0
            state['position_type'] = None
            state['position_entry'] = None
            state['sl_oid'] = None
            state['tp_oid'] = None
            state['slot_size'] = 0
            state['trail_high_water'] = None
            state['trail_low_water'] = None
            state['current_sl_price'] = None

        # ── Trailing Stop Loss ──────────────────────────────────
        if (slot_cfg.get('trailing_sl') and state['position_type']
                and current_price and state.get('position_entry')):
            self._update_trailing_sl(sid, state, symbol, current_price)

        # -- Fetch candles & run strategy -------------------------
        try:
            df = data.fetch_candles(
                symbol=symbol,
                interval=interval,
                limit=100,
            )
            if df is None or df.empty:
                return
        except Exception as e:
            self.root.after(0, self._log,
                f"[Slot #{sid} {symbol}] Market data error: {e}", "warn")
            return

        # Update chart with first slot
        if sid == min(self._slot_state.keys()):
            entry_p = state['position_entry']
            sl_pct = slot_cfg['sl']
            tp_pct = slot_cfg['tp']
            sl_p = entry_p * (1 - sl_pct / 100) if entry_p and state['position_type'] == "LONG" else (
                entry_p * (1 + sl_pct / 100) if entry_p else None
            )
            tp_p = entry_p * (1 + tp_pct / 100) if entry_p and state['position_type'] == "LONG" else (
                entry_p * (1 - tp_pct / 100) if entry_p else None
            )
            self.root.after(0, self.dashboard_tab.chart.update_chart,
                            df, symbol, 9, 21, entry_p, sl_p, tp_p)

        # Strategy signal
        signal = strategy.analyze(df, current_position=state['position_type'])
        state['last_signal'] = signal.signal_type.value
        self.root.after(0, self._log,
            f"[Slot #{sid} {symbol} {interval}] Signal: {signal.signal_type.value} "
            f"(str={signal.strength:.2f}) | {signal.reason}", "info")

        # News overrides
        if news_override == "bearish" and state['position_type'] == "LONG":
            self.root.after(0, self._log,
                f"[Slot #{sid}] News override → closing LONG", "warn")
            self._execute_slot(sid, SignalType.CLOSE_LONG,
                               "News sentiment override (bearish)", current_price)
            return
        elif news_override == "bullish" and state['position_type'] == "SHORT":
            self.root.after(0, self._log,
                f"[Slot #{sid}] News override → closing SHORT", "warn")
            self._execute_slot(sid, SignalType.CLOSE_SHORT,
                               "News sentiment override (bullish)", current_price)
            return

        # Act on signal (entry only – exits via on-chain SL/TP)
        if signal.signal_type == SignalType.HOLD:
            return

        if signal.signal_type in (SignalType.LONG, SignalType.SHORT):
            if state['position_type']:
                # Already in a position for this slot
                return

            # ── Contradictory signal blocking (multi-slot safe) ─
            # If another slot on the same symbol has an OPPOSITE position,
            # block entry to avoid on-chain position conflicts.
            desired_dir = "LONG" if signal.signal_type == SignalType.LONG else "SHORT"
            opposite = "SHORT" if desired_dir == "LONG" else "LONG"
            for other_sid, other_st in self._slot_state.items():
                if other_sid == sid:
                    continue
                if (other_st['config']['symbol'] == symbol
                        and other_st.get('position_type') == opposite):
                    self.root.after(0, self._log,
                        f"[Slot #{sid} {symbol}] Blocked {desired_dir} — "
                        f"Slot #{other_sid} has active {opposite}", "warn")
                    return

            if not risk_mgr.can_trade():
                self.root.after(0, self._log,
                    f"[Slot #{sid}] Daily loss limit reached", "warn")
                return
            # Block if news opposes
            if news_override == "bearish" and signal.signal_type == SignalType.LONG:
                self.root.after(0, self._log,
                    f"[Slot #{sid}] Blocked LONG due to bearish news", "warn")
                return
            if news_override == "bullish" and signal.signal_type == SignalType.SHORT:
                self.root.after(0, self._log,
                    f"[Slot #{sid}] Blocked SHORT due to bullish news", "warn")
                return

            # ── Loss Cooldown ───────────────────────────────────
            if slot_cfg.get('loss_cooldown'):
                cooldown_until = state.get('cooldown_until')
                if cooldown_until and datetime.now() < cooldown_until:
                    remaining = (cooldown_until - datetime.now()).seconds // 60
                    self.root.after(0, self._log,
                        f"[Slot #{sid} {symbol}] Cooldown active — "
                        f"{remaining}m remaining after {state['consecutive_losses']} losses",
                        "warn")
                    return
                if state.get('consecutive_losses', 0) >= 3:
                    state['cooldown_until'] = datetime.now() + timedelta(minutes=30)
                    self.root.after(0, self._log,
                        f"[Slot #{sid} {symbol}] ⏸ Cooldown triggered — "
                        f"3 consecutive losses, pausing 30 min", "warn")
                    return

            # ── ADX Regime Filter ───────────────────────────────
            if slot_cfg.get('regime_filter'):
                adx_val = self._calculate_adx(df)
                if adx_val is not None:
                    strategy_name = slot_cfg['strategy'].lower()
                    is_mean_reversion = 'rsi' in strategy_name or 'mean' in strategy_name
                    is_trend_following = 'ema' in strategy_name or 'crossover' in strategy_name or 'breakout' in strategy_name

                    if is_mean_reversion and adx_val > 25:
                        self.root.after(0, self._log,
                            f"[Slot #{sid} {symbol}] Blocked {signal.signal_type.value} "
                            f"— ADX={adx_val:.1f} (trending), mean-reversion disabled",
                            "warn")
                        return
                    if is_trend_following and adx_val < 20:
                        self.root.after(0, self._log,
                            f"[Slot #{sid} {symbol}] Blocked {signal.signal_type.value} "
                            f"— ADX={adx_val:.1f} (ranging), trend strategy disabled",
                            "warn")
                        return

            # ── RSI Exhaustion Guard ───────────────────────────
            # Blocks EMA/breakout entries at RSI extremes to avoid
            # shorting bottoms or longing tops.
            if slot_cfg.get('rsi_guard'):
                strategy_name = slot_cfg['strategy'].lower()
                is_non_rsi = ('ema' in strategy_name or 'crossover' in strategy_name
                              or 'breakout' in strategy_name)
                if is_non_rsi:
                    rsi_val = self._calculate_rsi(df)
                    if rsi_val is not None:
                        rsi_low = slot_cfg.get('rsi_guard_low', 30)
                        rsi_high = slot_cfg.get('rsi_guard_high', 70)
                        if signal.signal_type == SignalType.SHORT and rsi_val < rsi_low:
                            self.root.after(0, self._log,
                                f"[Slot #{sid} {symbol}] Blocked SHORT — "
                                f"RSI={rsi_val:.1f} < {rsi_low} (oversold, likely bottom)",
                                "warn")
                            return
                        if signal.signal_type == SignalType.LONG and rsi_val > rsi_high:
                            self.root.after(0, self._log,
                                f"[Slot #{sid} {symbol}] Blocked LONG — "
                                f"RSI={rsi_val:.1f} > {rsi_high} (overbought, likely top)",
                                "warn")
                            return

            # ── Volume Confirmation ─────────────────────────────
            if slot_cfg.get('volume_confirm'):
                if not self._check_volume_confirmation(df):
                    self.root.after(0, self._log,
                        f"[Slot #{sid} {symbol}] Blocked {signal.signal_type.value} "
                        f"— volume below 1.5× average", "warn")
                    return

            # ── Multi-Timeframe Confirmation ────────────────────
            if slot_cfg.get('mtf_enabled', True):
                htf = Config.MTF_MAP.get(interval)
                if htf and htf != interval:
                    mtf_ok = self._check_mtf_alignment(
                        symbol, htf, signal.signal_type, data)
                    if not mtf_ok:
                        self.root.after(0, self._log,
                            f"[Slot #{sid} {symbol}] Blocked {signal.signal_type.value} "
                            f"— higher TF ({htf}) EMA misaligned", "warn")
                        return

            # Cache ATR for ATR-based stops (used in _execute_slot)
            if slot_cfg.get('atr_stops'):
                state['last_atr'] = self._calculate_atr(df)

            self._execute_slot(sid, signal.signal_type, signal.reason, current_price)

        # Update sidebar stats
        self.root.after(0, self.sidebar.update_stats,
                        self._daily_pnl, self._total_trades,
                        self._wins, state['last_signal'])

    def _check_news_override(self) -> Optional[str]:
        """
        Check if recent news should override the strategy.
        Returns 'bearish', 'bullish', or None.
        """
        if not self._news_monitor:
            return None

        # If any CRITICAL bearish event in last 5 minutes → override
        critical = self._news_monitor.get_critical_items(since_minutes=5)
        for item in critical:
            if item.sentiment == "bearish":
                return "bearish"
            if item.sentiment == "bullish":
                return "bullish"

        # If strong sentiment bias from HIGH items in last 30 min
        bias = self._news_monitor.get_sentiment_bias(window_minutes=30)
        if bias != "neutral":
            return bias

        return None

    def _execute_slot(self, sid: int, signal: SignalType, reason: str,
                       current_price: float):
        """Execute a trade for a specific slot (called from bot thread)."""
        state = self._slot_state.get(sid)
        if not state:
            return

        slot_cfg = state['config']
        symbol = slot_cfg['symbol']
        size_usd = slot_cfg.get('size_usd', 100)
        client = self._client_for(symbol)

        try:
            if signal == SignalType.LONG:
                order_resp = client.place_market_order(
                    symbol, is_buy=True,
                    size_usd=size_usd,
                    leverage=slot_cfg['leverage'],
                )
                if not order_resp:
                    self.root.after(0, self._log,
                        f"✗ [Slot #{sid} {symbol}] LONG order failed", "error")
                    return
                fill_px, fill_sz = self._extract_fill(order_resp, current_price)
                self.root.after(0, self._log,
                    f"✓ [Slot #{sid} {symbol}] LONG opened (${size_usd}) "
                    f"@ ${fill_px:,.2f}: {reason}", "long")
                self._record_trade(symbol, "LONG", reason, slot_id=sid)

                # Place on-chain SL/TP trigger orders
                self._place_sl_tp(sid, symbol, is_long=True,
                                  entry_price=fill_px, slot_cfg=slot_cfg,
                                  fill_size=fill_sz)

                # Email notification
                if self._email:
                    self._email.notify_open(
                        symbol=symbol, side="LONG",
                        size_usd=size_usd,
                        entry_price=fill_px,
                        leverage=slot_cfg['leverage'],
                        sl_pct=slot_cfg['sl'], tp_pct=slot_cfg['tp'],
                        reason=reason, slot_id=sid,
                    )
                # Telegram notification
                if self._telegram:
                    self._telegram.notify_open(
                        symbol=symbol, side="LONG",
                        size_usd=size_usd,
                        entry_price=fill_px,
                        leverage=slot_cfg['leverage'],
                        sl_pct=slot_cfg['sl'], tp_pct=slot_cfg['tp'],
                        reason=reason, slot_id=sid,
                    )

                # Set per-slot position state
                state['position_type'] = 'LONG'
                state['position_entry'] = fill_px

                # Initialise trailing SL state
                state['trail_high_water'] = fill_px
                state['trail_low_water'] = None

            elif signal == SignalType.SHORT:
                order_resp = client.place_market_order(
                    symbol, is_buy=False,
                    size_usd=size_usd,
                    leverage=slot_cfg['leverage'],
                )
                if not order_resp:
                    self.root.after(0, self._log,
                        f"✗ [Slot #{sid} {symbol}] SHORT order failed", "error")
                    return
                fill_px, fill_sz = self._extract_fill(order_resp, current_price)
                self.root.after(0, self._log,
                    f"✓ [Slot #{sid} {symbol}] SHORT opened (${size_usd}) "
                    f"@ ${fill_px:,.2f}: {reason}", "short")
                self._record_trade(symbol, "SHORT", reason, slot_id=sid)

                # Place on-chain SL/TP trigger orders
                self._place_sl_tp(sid, symbol, is_long=False,
                                  entry_price=fill_px, slot_cfg=slot_cfg,
                                  fill_size=fill_sz)

                if self._email:
                    self._email.notify_open(
                        symbol=symbol, side="SHORT",
                        size_usd=size_usd,
                        entry_price=fill_px,
                        leverage=slot_cfg['leverage'],
                        sl_pct=slot_cfg['sl'], tp_pct=slot_cfg['tp'],
                        reason=reason, slot_id=sid,
                    )
                if self._telegram:
                    self._telegram.notify_open(
                        symbol=symbol, side="SHORT",
                        size_usd=size_usd,
                        entry_price=fill_px,
                        leverage=slot_cfg['leverage'],
                        sl_pct=slot_cfg['sl'], tp_pct=slot_cfg['tp'],
                        reason=reason, slot_id=sid,
                    )

                # Set per-slot position state
                state['position_type'] = 'SHORT'
                state['position_entry'] = fill_px

                # Initialise trailing SL state
                state['trail_high_water'] = None
                state['trail_low_water'] = fill_px

            elif signal in (SignalType.CLOSE_LONG, SignalType.CLOSE_SHORT):
                entry_price = state.get('position_entry') or current_price
                side = "LONG" if signal == SignalType.CLOSE_LONG else "SHORT"

                # Cancel outstanding SL/TP trigger orders before closing
                self._cancel_sl_tp(sid, symbol)

                # Use partial close when other slots share this symbol
                slot_sz = state.get('slot_size', 0)
                other_active = any(
                    s.get('slot_size', 0) > 0
                    for osid, s in self._slot_state.items()
                    if osid != sid and s['config']['symbol'] == symbol
                )
                if other_active and slot_sz > 0:
                    is_long_pos = (side == 'LONG')
                    client.close_partial_position(symbol, slot_sz, is_long_pos)
                else:
                    client.close_position(symbol)
                self.root.after(0, self._log,
                    f"✓ [Slot #{sid} {symbol}] Position closed: {reason}", "info")
                self._record_trade(symbol, "CLOSE", reason, slot_id=sid)

                # Calculate P&L for email
                if side == "LONG":
                    pnl = (current_price - entry_price) / entry_price * size_usd
                else:
                    pnl = (entry_price - current_price) / entry_price * size_usd

                if self._email:
                    self._email.notify_close(
                        symbol=symbol, side=side,
                        entry_price=entry_price,
                        exit_price=current_price,
                        pnl=pnl, reason=reason, slot_id=sid,
                    )
                if self._telegram:
                    self._telegram.notify_close(
                        symbol=symbol, side=side,
                        entry_price=entry_price,
                        exit_price=current_price,
                        pnl=pnl, reason=reason, slot_id=sid,
                    )

                state['position_type'] = None
                state['position_entry'] = None
                state['sl_oid'] = None
                state['tp_oid'] = None
                state['slot_size'] = 0
                state['trail_high_water'] = None
                state['trail_low_water'] = None
                state['current_sl_price'] = None

            time.sleep(2)  # settle

        except Exception as e:
            self.root.after(0, self._log,
                f"[Slot #{sid} {symbol}] Trade error: {e}", "error")

    @staticmethod
    def _extract_fill(order_resp, fallback_price: float):
        """Extract fill price and size from a market order response.

        Returns (fill_price, fill_size) — fill_size may be 0 if not available.
        """
        try:
            if isinstance(order_resp, dict):
                statuses = (order_resp.get("response", {})
                            .get("data", {}).get("statuses", []))
                if statuses and isinstance(statuses[0], dict):
                    filled = statuses[0].get("filled", {})
                    px = float(filled.get("avgPx", 0))
                    sz = float(filled.get("totalSz", 0))
                    if px > 0:
                        return px, sz
        except (ValueError, TypeError, KeyError):
            pass
        return fallback_price, 0.0

    # ── SL/TP trigger-order helpers ─────────────────────────────
    def _place_sl_tp(self, sid: int, symbol: str, is_long: bool,
                     entry_price: float, slot_cfg: dict,
                     fill_size: float = 0.0):
        """Place on-chain SL and TP trigger orders right after entry."""
        try:
            # Determine SL/TP percentages — ATR-based or fixed
            sl_pct = slot_cfg['sl']
            tp_pct = slot_cfg['tp']
            state = self._slot_state.get(sid, {})

            if slot_cfg.get('atr_stops') and state.get('last_atr'):
                atr = state['last_atr']
                # SL = 2×ATR, TP = 3×ATR (1.5:1 reward-to-risk)
                atr_sl_pct = (atr * 2 / entry_price) * 100
                atr_tp_pct = (atr * 3 / entry_price) * 100
                # Clamp to sensible bounds (0.1% – 15%)
                sl_pct = max(0.1, min(atr_sl_pct, 15.0))
                tp_pct = max(0.15, min(atr_tp_pct, 20.0))
                logger.info(f"[Slot #{sid} {symbol}] ATR-based stops: "
                            f"ATR={atr:.4f}, SL={sl_pct:.2f}%, TP={tp_pct:.2f}%")
                self.root.after(0, self._log,
                    f"[Slot #{sid} {symbol}] ATR stops: SL={sl_pct:.2f}% "
                    f"TP={tp_pct:.2f}% (ATR={atr:.2f})", "info")

            logger.info(f"[Slot #{sid} {symbol}] Placing SL/TP: "
                        f"entry={entry_price}, is_long={is_long}, "
                        f"fill_size={fill_size}, sl={sl_pct}%, tp={tp_pct}%")
            client = self._client_for(symbol)

            # Use fill size from order response; fall back to querying position
            size = fill_size
            if size <= 0:
                time.sleep(1)  # brief settle before querying
                size = client.get_position_size(symbol)
                logger.info(f"[Slot #{sid} {symbol}] Queried position size: {size}")
            if size <= 0:
                self.root.after(0, self._log,
                    f"[Slot #{sid}] Warning: could not read position size for SL/TP "
                    "(will retry once)", "warn")
                time.sleep(2)
                size = client.get_position_size(symbol)
                if size <= 0:
                    logger.error(f"[Slot #{sid} {symbol}] SL/TP skipped – position size still 0")
                    self.root.after(0, self._log,
                        f"[Slot #{sid}] SL/TP skipped – position size still 0", "error")
                    return

            results = client.place_sl_tp_orders(
                symbol=symbol,
                is_long=is_long,
                entry_price=entry_price,
                size=size,
                sl_pct=sl_pct,
                tp_pct=tp_pct,
            )

            sl_ok = results.get('sl') is not None
            tp_ok = results.get('tp') is not None

            # Store order IDs for per-slot cancellation
            if sid in self._slot_state:
                self._slot_state[sid]['sl_oid'] = results.get('sl_oid')
                self._slot_state[sid]['tp_oid'] = results.get('tp_oid')
                self._slot_state[sid]['slot_size'] = size
                logger.info(f"[Slot #{sid} {symbol}] Stored oids: "
                            f"sl_oid={results.get('sl_oid')}, "
                            f"tp_oid={results.get('tp_oid')}, "
                            f"slot_size={size}")

            from core.exchange import HyperliquidClient
            _rp = HyperliquidClient._round_trigger_price
            if is_long:
                sl_px = _rp(entry_price * (1 - sl_pct / 100))
                tp_px = _rp(entry_price * (1 + tp_pct / 100))
            else:
                sl_px = _rp(entry_price * (1 + sl_pct / 100))
                tp_px = _rp(entry_price * (1 - tp_pct / 100))

            status = (f"SL@${sl_px:,.2f} {'✓' if sl_ok else '✗ FAILED'}  "
                       f"TP@${tp_px:,.2f} {'✓' if tp_ok else '✗ FAILED'}")
            tag = "info" if (sl_ok and tp_ok) else "error"
            logger.info(f"[Slot #{sid} {symbol}] SL/TP result: {status}")
            self.root.after(0, self._log,
                f"[Slot #{sid} {symbol}] On-chain orders: {status} (size={size})", tag)

            # Store current SL price for trailing SL tracking
            if sl_ok and sid in self._slot_state:
                self._slot_state[sid]['current_sl_price'] = sl_px

        except Exception as e:
            logger.error(f"[Slot #{sid} {symbol}] SL/TP placement error: {e}", exc_info=True)
            self.root.after(0, self._log,
                f"[Slot #{sid} {symbol}] SL/TP placement error: {e}", "error")

    def _cancel_sl_tp(self, sid: int, symbol: str):
        """Cancel this slot's SL/TP trigger orders by stored oid.

        Falls back to cancel-all only if no other slot shares this symbol.
        """
        try:
            client = self._client_for(symbol)
            state = self._slot_state.get(sid, {})
            sl_oid = state.get('sl_oid')
            tp_oid = state.get('tp_oid')
            cancelled_any = False

            if sl_oid:
                if client.cancel_order_by_id(symbol, sl_oid):
                    cancelled_any = True
                state['sl_oid'] = None
            if tp_oid:
                if client.cancel_order_by_id(symbol, tp_oid):
                    cancelled_any = True
                state['tp_oid'] = None

            if not sl_oid and not tp_oid:
                # No stored oids — check if another slot shares this symbol
                other_slots_same_sym = [
                    s for s_id, s in self._slot_state.items()
                    if s_id != sid and s['config']['symbol'] == symbol
                ]
                if not other_slots_same_sym:
                    # Safe to nuke all orders for this symbol
                    client.cancel_open_orders(symbol)
                    cancelled_any = True
                else:
                    logger.warning(f"[Slot #{sid} {symbol}] No oids stored and "
                                   f"other slots share symbol — skipping cancel-all")

            if cancelled_any:
                self.root.after(0, self._log,
                    f"[Slot #{sid} {symbol}] Cancelled SL/TP trigger orders", "info")
        except Exception as e:
            self.root.after(0, self._log,
                f"[Slot #{sid} {symbol}] Error cancelling SL/TP: {e}", "warn")

    # ── Telegram Command Callbacks ──────────────────────────────
    def _tg_cmd_status(self) -> str:
        """Handle /status — show all positions, P&L, balance."""
        try:
            lines = ["📊 *Bot Status*\n━━━━━━━━━━━━━━━"]
            if not self._bot_running:
                lines.append("⚠️ Bot is *stopped*")
            else:
                lines.append("✅ Bot is *running*")

            # Balance
            balance = 0.0
            if self._client:
                try:
                    balance = self._client.get_balance()
                except Exception:
                    pass
            lines.append(f"💰 Balance: `${balance:,.2f}`")
            lines.append(f"📈 Session P&L: `${self._daily_pnl:+,.2f}`")
            lines.append(f"🔢 Total trades: `{self._total_trades}`")

            # Positions
            open_count = 0
            for sid, state in sorted(self._slot_state.items()):
                pos_type = state.get('position_type')
                if pos_type:
                    open_count += 1
                    symbol = state['config']['symbol']
                    entry = state.get('position_entry', 0)
                    try:
                        price = self._client_for(symbol).get_market_price(symbol) or 0
                    except Exception:
                        price = 0
                    if entry and price:
                        pnl_pct = ((price - entry) / entry * 100)
                        if pos_type == 'SHORT':
                            pnl_pct = -pnl_pct
                    else:
                        pnl_pct = 0
                    emoji = "🟢" if pnl_pct >= 0 else "🔴"
                    lines.append(
                        f"\n{emoji} *Slot #{sid} — {symbol}*\n"
                        f"  {pos_type} @ `${entry:,.2f}`\n"
                        f"  Price: `${price:,.2f}` | `{pnl_pct:+.2f}%`"
                    )

            if open_count == 0:
                lines.append("\n_No open positions_")

            return "\n".join(lines)
        except Exception as e:
            logger.error(f"Telegram /status error: {e}", exc_info=True)
            return f"❌ Error: {e}"

    def _tg_cmd_stop(self) -> str:
        """Handle /stop — stop the bot."""
        if not self._bot_running:
            return "⚠️ Bot is already stopped."
        self.root.after(0, self._on_stop)
        return "🛑 Bot stopping..."

    def _tg_cmd_start(self) -> str:
        """Handle /start — start the bot."""
        if self._bot_running:
            return "✅ Bot is already running."
        self.root.after(0, self._on_start)
        return "🚀 Bot starting..."

    def _tg_cmd_close(self, target: str) -> str:
        """Handle /close [symbol|all] — close specific or all positions."""
        if not self._clients:
            return "⚠️ Bot not connected. Start it first."

        target = target.upper()
        if target == "ALL":
            self.root.after(0, self._on_close_position)
            return "🔄 Closing all positions..."

        # Find matching slot(s)
        matched = []
        for sid, state in list(self._slot_state.items()):
            sym = state['config']['symbol']
            # Match by exact name or stripped prefix
            # Strip any HIP-3 dex prefix for fuzzy matching
            sym_clean = sym.split(":", 1)[-1].upper() if ":" in sym else sym.upper()
            if sym_clean == target or sym.upper() == target:
                matched.append((sid, state))

        if not matched:
            known = ', '.join(
                state['config']['symbol'] for state in self._slot_state.values()
            )
            return f"❌ No slot found for `{target}`.\nActive symbols: {known}"

        closed = []
        for sid, state in matched:
            symbol = state['config']['symbol']
            try:
                client = self._client_for(symbol)
                self._cancel_sl_tp(sid, symbol)

                # Partial close when other slots share this symbol
                slot_sz = state.get('slot_size', 0)
                other_active = any(
                    s.get('slot_size', 0) > 0
                    for osid, s in self._slot_state.items()
                    if osid != sid and s['config']['symbol'] == symbol
                )
                if other_active and slot_sz > 0:
                    is_long_pos = state.get('position_type') == 'LONG'
                    result = client.close_partial_position(symbol, slot_sz, is_long_pos)
                else:
                    result = client.close_position(symbol)

                if result:
                    entry = state.get('position_entry', 0)
                    price = client.get_market_price(symbol) or 0
                    if self._telegram and entry:
                        self._telegram.notify_close(
                            symbol=symbol,
                            side=state.get('position_type', 'LONG'),
                            entry_price=entry,
                            exit_price=price,
                            reason="Telegram /close", slot_id=sid,
                        )
                    state['position_type'] = None
                    state['position_entry'] = None
                    state['sl_oid'] = None
                    state['tp_oid'] = None
                    state['slot_size'] = 0
                    state['trail_high_water'] = None
                    state['trail_low_water'] = None
                    state['current_sl_price'] = None
                    closed.append(symbol)
                    self.root.after(0, self._log,
                        f"[Slot #{sid}] {symbol} closed via Telegram", "warn")
            except Exception as e:
                logger.error(f"Telegram /close {symbol} error: {e}")
                return f"❌ Error closing {symbol}: {e}"

        if closed:
            return f"✅ Closed: {', '.join(closed)}"
        return f"ℹ️ No open position on `{target}` to close."

    def _tg_cmd_slots(self) -> str:
        """Handle /slots — show active slot configurations."""
        try:
            if not self._slot_state:
                return "⚠️ No active slots. Bot may not be running."

            lines = ["⚙️ *Slot Configurations*\n━━━━━━━━━━━━━━━"]
            for sid, state in sorted(self._slot_state.items()):
                cfg = state['config']
                pos = state.get('position_type') or '—'
                trail = "✓" if cfg.get('trailing_sl') else "✗"
                mtf = "✓" if cfg.get('mtf_enabled') else "✗"
                sp = cfg.get('strategy_params', {})
                params_str = ", ".join(f"{k}={v}" for k, v in sp.items()) if sp else "default"

                adx_icon = "✓" if cfg.get('regime_filter') else "✗"
                atr_icon = "✓" if cfg.get('atr_stops') else "✗"
                cd_icon = "✓" if cfg.get('loss_cooldown') else "✗"
                vol_icon = "✓" if cfg.get('volume_confirm') else "✗"
                rsi_g_icon = "✓" if cfg.get('rsi_guard') else "✗"

                lines.append(
                    f"\n*Slot #{sid} — {cfg['symbol']}*\n"
                    f"  Strategy: `{cfg['strategy']}` ({params_str})\n"
                    f"  Interval: `{cfg['interval']}`\n"
                    f"  Size: `${cfg.get('size_usd', 100)}` @ `{cfg['leverage']}x`\n"
                    f"  SL: `{cfg['sl']}%` | TP: `{cfg['tp']}%`\n"
                    f"  Trail: {trail} | MTF: {mtf} | ADX: {adx_icon}\n"
                    f"  ATR-SL: {atr_icon} | Cooldown: {cd_icon} | Vol: {vol_icon}\n"
                    f"  RSI Guard: {rsi_g_icon}\n"
                    f"  Position: {pos}"
                )
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"Telegram /slots error: {e}", exc_info=True)
            return f"❌ Error: {e}"

    # ── Trailing Stop Loss ──────────────────────────────────────
    def _update_trailing_sl(self, sid: int, state: dict,
                            symbol: str, current_price: float):
        """
        Check if the trailing SL should be moved closer to price.

        For LONG positions: track the high-water mark. When price makes a new
        high, calculate a new SL = high * (1 − sl_pct/100). If that new SL is
        higher than the current on-chain SL, cancel-and-replace.

        For SHORT positions: mirror logic with low-water mark.
        """
        from core.exchange import HyperliquidClient
        _rp = HyperliquidClient._round_trigger_price

        slot_cfg = state['config']
        sl_pct = slot_cfg['sl']
        pos_type = state['position_type']
        client = self._client_for(symbol)

        if pos_type == "LONG":
            old_hw = state.get('trail_high_water') or current_price
            if current_price > old_hw:
                state['trail_high_water'] = current_price
            hw = state['trail_high_water']
            new_sl = _rp(hw * (1 - sl_pct / 100))
            cur_sl = state.get('current_sl_price')

            if cur_sl is None:
                # First time — record the initial SL
                entry = state.get('position_entry', current_price)
                state['current_sl_price'] = _rp(entry * (1 - sl_pct / 100))
                return

            if new_sl > cur_sl:
                # Move SL up
                self._replace_sl_order(sid, state, symbol, new_sl, is_long=True, client=client)

        elif pos_type == "SHORT":
            old_lw = state.get('trail_low_water') or current_price
            if current_price < old_lw:
                state['trail_low_water'] = current_price
            lw = state['trail_low_water']
            new_sl = _rp(lw * (1 + sl_pct / 100))
            cur_sl = state.get('current_sl_price')

            if cur_sl is None:
                entry = state.get('position_entry', current_price)
                state['current_sl_price'] = _rp(entry * (1 + sl_pct / 100))
                return

            if new_sl < cur_sl:
                # Move SL down (tighter for shorts)
                self._replace_sl_order(sid, state, symbol, new_sl, is_long=False, client=client)

    def _replace_sl_order(self, sid: int, state: dict, symbol: str,
                          new_sl: float, is_long: bool,
                          client: "HyperliquidClient"):
        """Cancel this slot's SL trigger order and place a new one at new_sl.

        Only cancels/replaces this slot's orders by oid, preserving other
        slots' orders on the same symbol.
        """
        try:
            old_sl = state.get('current_sl_price', 0)
            from core.exchange import HyperliquidClient
            _rp = HyperliquidClient._round_trigger_price

            # Cancel only THIS slot's SL and TP by oid
            sl_oid = state.get('sl_oid')
            tp_oid = state.get('tp_oid')
            if sl_oid:
                client.cancel_order_by_id(symbol, sl_oid)
                state['sl_oid'] = None
            if tp_oid:
                client.cancel_order_by_id(symbol, tp_oid)
                state['tp_oid'] = None

            # Use this slot's tracked size (not total position)
            size = state.get('slot_size', 0)
            if size <= 0:
                size = client.get_position_size(symbol)
            if size <= 0:
                return

            # Re-place SL at the new trailing price
            sl_buy = not is_long
            sl_result = client.place_trigger_order(
                symbol, sl_buy, size, new_sl, tpsl="sl")

            # Re-place TP at original level
            slot_cfg = state['config']
            entry = state.get('position_entry', 0)
            if is_long:
                tp_price = _rp(entry * (1 + slot_cfg['tp'] / 100))
            else:
                tp_price = _rp(entry * (1 - slot_cfg['tp'] / 100))
            tp_buy = not is_long
            tp_result = client.place_trigger_order(
                symbol, tp_buy, size, tp_price, tpsl="tp")

            # Store new oids
            state['sl_oid'] = HyperliquidClient.extract_oid(sl_result)
            state['tp_oid'] = HyperliquidClient.extract_oid(tp_result)

            if sl_result:
                state['current_sl_price'] = new_sl
                self.root.after(0, self._log,
                    f"[Slot #{sid} {symbol}] 🔄 Trailing SL: ${old_sl:,.2f} → ${new_sl:,.2f}",
                    "info")
                if self._telegram:
                    self._telegram.notify_trailing_sl_update(
                        symbol=symbol, old_sl=old_sl, new_sl=new_sl,
                        current_price=state.get('trail_high_water') or state.get('trail_low_water') or 0,
                        slot_id=sid,
                    )
            else:
                self.root.after(0, self._log,
                    f"[Slot #{sid} {symbol}] Trailing SL update FAILED", "error")

        except Exception as e:
            logger.error(f"[Slot #{sid} {symbol}] Trailing SL error: {e}", exc_info=True)
            self.root.after(0, self._log,
                f"[Slot #{sid} {symbol}] Trailing SL error: {e}", "error")

    # ── Multi-Timeframe Confirmation ────────────────────────────
    def _check_mtf_alignment(self, symbol: str, htf_interval: str,
                             signal_type: "SignalType",
                             data: "MarketData") -> bool:
        """
        Check if the higher-timeframe trend aligns with the entry signal.

        Uses a 21-EMA on the higher TF: if EMA is rising → bullish, falling → bearish.
        Returns True if aligned (or if data unavailable → allow trade).
        """
        try:
            df_htf = data.fetch_candles(symbol=symbol, interval=htf_interval, limit=50)
            if df_htf is None or len(df_htf) < 22:
                return True  # not enough data — don't block

            ema21 = df_htf['close'].ewm(span=21, adjust=False).mean()
            current_ema = ema21.iloc[-1]
            prev_ema = ema21.iloc[-2]

            ema_rising = current_ema > prev_ema

            if signal_type == SignalType.LONG:
                return ema_rising
            elif signal_type == SignalType.SHORT:
                return not ema_rising

            return True  # unknown signal type → allow

        except Exception as e:
            logger.error(f"MTF check error ({symbol} {htf_interval}): {e}")
            return True  # on error, don't block the trade

    # ── RSI Exhaustion Guard ──────────────────────────────────────
    @staticmethod
    def _calculate_rsi(df, period: int = 14) -> float | None:
        """Calculate RSI(period) from the close column.

        Returns the latest RSI value (0-100), or None if insufficient data.
        """
        try:
            if 'close' not in df.columns or len(df) < period + 1:
                return None
            closes = df['close'].astype(float)
            delta = closes.diff()
            gain = delta.clip(lower=0)
            loss = -delta.clip(upper=0)

            avg_gain = gain.iloc[1:period + 1].mean()
            avg_loss = loss.iloc[1:period + 1].mean()

            for i in range(period + 1, len(delta)):
                avg_gain = (avg_gain * (period - 1) + gain.iloc[i]) / period
                avg_loss = (avg_loss * (period - 1) + loss.iloc[i]) / period

            if avg_loss == 0:
                return 100.0
            rs = avg_gain / avg_loss
            return 100.0 - (100.0 / (1.0 + rs))
        except Exception:
            return None

    # ── ADX Regime Filter ───────────────────────────────────────
    @staticmethod
    def _calculate_adx(df, period: int = 14) -> float | None:
        """
        Calculate the Average Directional Index (ADX) from OHLC data.

        ADX > 25 → trending market  (favour trend-following)
        ADX < 20 → ranging market   (favour mean-reversion)

        Returns the latest ADX value, or None if insufficient data.
        """
        try:
            if len(df) < period * 2 + 1:
                return None

            high = df['high']
            low = df['low']
            close = df['close']

            # True Range
            tr1 = high - low
            tr2 = (high - close.shift(1)).abs()
            tr3 = (low - close.shift(1)).abs()
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

            # Directional Movement
            up_move = high - high.shift(1)
            down_move = low.shift(1) - low
            plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
            minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

            # Smoothed averages (Wilder's smoothing)
            atr = tr.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
            plus_di = 100 * (plus_dm.ewm(alpha=1/period, min_periods=period, adjust=False).mean() / atr)
            minus_di = 100 * (minus_dm.ewm(alpha=1/period, min_periods=period, adjust=False).mean() / atr)

            # Directional Index
            dx = (plus_di - minus_di).abs() / (plus_di + minus_di) * 100
            dx = dx.replace([float('inf'), float('-inf')], 0).fillna(0)

            # ADX = smoothed DX
            adx = dx.ewm(alpha=1/period, min_periods=period, adjust=False).mean()

            val = adx.iloc[-1]
            return float(val) if pd.notna(val) else None
        except Exception as e:
            logger.error(f"ADX calculation error: {e}")
            return None

    # ── ATR Calculation ─────────────────────────────────────────
    @staticmethod
    def _calculate_atr(df, period: int = 14) -> float | None:
        """
        Calculate Average True Range (ATR) for volatility-adjusted stops.

        Returns the current ATR value in price units, or None.
        """
        try:
            if len(df) < period + 1:
                return None

            high = df['high']
            low = df['low']
            close = df['close']

            tr1 = high - low
            tr2 = (high - close.shift(1)).abs()
            tr3 = (low - close.shift(1)).abs()
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

            atr = tr.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
            val = atr.iloc[-1]
            return float(val) if pd.notna(val) else None
        except Exception as e:
            logger.error(f"ATR calculation error: {e}")
            return None

    # ── Volume Confirmation ─────────────────────────────────────
    @staticmethod
    def _check_volume_confirmation(df, lookback: int = 20,
                                    multiplier: float = 1.5) -> bool:
        """
        Check if the current candle's volume is above average.

        Returns True if volume >= multiplier × SMA(volume, lookback).
        If volume data is missing or insufficient, returns True (don't block).
        """
        try:
            if 'volume' not in df.columns or len(df) < lookback + 1:
                return True

            vol = df['volume']
            avg_vol = vol.iloc[-lookback - 1:-1].mean()  # exclude current candle
            curr_vol = vol.iloc[-1]

            if avg_vol <= 0:
                return True

            return curr_vol >= avg_vol * multiplier
        except Exception:
            return True

    def _record_trade(self, symbol: str, side: str, reason: str,
                      slot_id: int | None = None):
        """Record a trade in the log tab + update stats."""
        self._total_trades += 1
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        price = self._prev_price or 0
        slot_label = f"[#{slot_id}] " if slot_id is not None else ""

        self.root.after(0, self.log_tab.add_trade,
                        now, f"{slot_label}{symbol}", side, "--",
                        f"${price:,.2f}", "--", reason)

    # ════════════════════════════════════════════════════════════
    #  Periodic UI refresh (runs on main thread via after())
    # ════════════════════════════════════════════════════════════
    def _schedule_ui_updates(self):
        """Schedule periodic GUI refreshes."""
        self._update_market_stats()
        self.root.after(5000, self._schedule_ui_updates)

    def _update_market_stats(self):
        """Refresh market-info table for every active slot."""
        if not self._clients:
            return
        try:
            for sid, state in list(self._slot_state.items()):
                symbol = state['config']['symbol']
                slot_cfg = state['config']
                client = self._client_for(symbol)

                ctx = client.get_asset_context(symbol)
                if not ctx:
                    self.dashboard_tab.update_market_stats(
                        symbol=symbol, volume="--", funding="--",
                        oi="--", change_24h="--",
                        leverage=f"{slot_cfg.get('leverage', 1)}x",
                    )
                    continue

                # 24h volume
                day_vlm = float(ctx.get("dayNtlVlm", 0))
                if day_vlm >= 1_000_000_000:
                    vol_str = f"${day_vlm / 1_000_000_000:.2f}B"
                elif day_vlm >= 1_000_000:
                    vol_str = f"${day_vlm / 1_000_000:.2f}M"
                elif day_vlm >= 1_000:
                    vol_str = f"${day_vlm / 1_000:.2f}K"
                else:
                    vol_str = f"${day_vlm:,.0f}"

                # Funding rate (annualised display)
                funding_raw = float(ctx.get("funding", 0))
                funding_pct = funding_raw * 100
                fund_str = f"{funding_pct:+.4f}%"

                # Open interest (notional)
                oi_raw = float(ctx.get("openInterest", 0))
                mark = float(ctx.get("markPx", 0)) or 1
                oi_usd = oi_raw * mark
                if oi_usd >= 1_000_000_000:
                    oi_str = f"${oi_usd / 1_000_000_000:.2f}B"
                elif oi_usd >= 1_000_000:
                    oi_str = f"${oi_usd / 1_000_000:.2f}M"
                elif oi_usd >= 1_000:
                    oi_str = f"${oi_usd / 1_000:.2f}K"
                else:
                    oi_str = f"${oi_usd:,.0f}"

                # 24h price change
                prev_px = float(ctx.get("prevDayPx", 0))
                if prev_px > 0 and mark > 0:
                    chg = (mark - prev_px) / prev_px * 100
                    chg_str = f"{chg:+.2f}%"
                else:
                    chg_str = "--"

                # Mark price
                price_str = f"${mark:,.2f}" if mark < 10_000 else f"${mark:,.0f}"

                lev = slot_cfg.get('leverage', ctx.get("maxLeverage", 1))
                self.dashboard_tab.update_market_stats(
                    symbol=symbol,
                    volume=vol_str,
                    funding=fund_str,
                    oi=oi_str,
                    change_24h=chg_str,
                    leverage=f"{lev}x",
                    price=price_str,
                )

            # Update sidebar stats
            self.sidebar.update_stats(
                self._daily_pnl, self._total_trades,
                self._wins, self._last_signal,
            )
        except Exception:
            pass

    # ════════════════════════════════════════════════════════════
    #  Logging helper
    # ════════════════════════════════════════════════════════════
    def _log(self, message: str, tag: str = "info"):
        """Append to the trade log widget + Python logger."""
        ts = datetime.now().strftime("%H:%M:%S")
        try:
            self.log_tab.log.append(ts, message, tag)
        except Exception:
            pass
        logger.info(message)

    # ════════════════════════════════════════════════════════════
    #  Shutdown
    # ════════════════════════════════════════════════════════════
    def _on_close(self):
        """Graceful shutdown."""
        if self._bot_running:
            self._on_stop()

        if self._news_monitor:
            self._news_monitor.stop()

        if self._outcome_monitor:
            self._outcome_monitor.stop()

        self.root.destroy()

    # ════════════════════════════════════════════════════════════
    #  Run
    # ════════════════════════════════════════════════════════════
    def run(self):
        """Start the Tk main loop."""
        self.root.mainloop()


# ================================================================
def main():
    app = DashboardApp()
    app.run()


if __name__ == "__main__":
    main()
