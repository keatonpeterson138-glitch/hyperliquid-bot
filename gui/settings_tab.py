"""Settings tab – all configuration parameters with save/load."""
from __future__ import annotations
import tkinter as tk
from tkinter import messagebox
from gui.theme import *
from gui.components import Card, LabelledEntry, LabelledCombo, ActionButton
from config import Config
from strategies.factory import STRATEGY_DEFAULTS

SYMBOLS = ["BTC", "ETH", "SOL", "HYPE", "DOGE", "AVAX", "LINK", "ARB",
           "cash:GOLD", "cash:SILVER", "cash:TSLA", "cash:NVDA", "cash:USA500",
           "xyz:SP500", "xyz:TSLA", "xyz:NVDA", "xyz:AAPL", "xyz:MSFT",
           "xyz:GOOGL", "xyz:AMZN", "xyz:META", "xyz:AMD", "xyz:GOLD",
           "xyz:SILVER", "xyz:PLTR", "xyz:COIN", "xyz:HOOD", "xyz:MSTR",
           "xyz:NFLX", "xyz:INTC", "xyz:COST", "xyz:ORCL", "xyz:LLY",
           "xyz:TSM", "xyz:CL", "xyz:COPPER", "xyz:NATGAS", "xyz:PLATINUM",
           "xyz:PALLADIUM", "xyz:BRENTOIL", "xyz:JPY", "xyz:EUR",
           "xyz:BABA", "xyz:MU", "xyz:SNDK", "xyz:CRCL", "xyz:SKHX",
           "xyz:RIVN", "xyz:SMSN", "xyz:USAR", "xyz:CRWV", "xyz:URNM",
           "xyz:KR200", "xyz:JP225", "xyz:HYUNDAI", "xyz:EWY", "xyz:EWJ",
           "xyz:HIMS", "xyz:DKNG", "xyz:BIRD", "xyz:XYZ100"]
INTERVALS = ["1m", "5m", "15m", "1h", "4h", "1d"]
STRATEGIES = ["ema_crossover", "rsi_mean_reversion", "breakout"]

# Human-readable labels for strategy parameters
_PARAM_LABELS = {
    'fast_period': 'EMA Fast',
    'slow_period': 'EMA Slow',
    'period': 'RSI Period',
    'oversold': 'Oversold',
    'overbought': 'Overbought',
    'lookback_period': 'Lookback',
    'breakout_threshold_pct': 'Breakout %',
}


class _SlotRow(tk.Frame):
    """One position-slot configuration row."""

    def __init__(self, parent, slot_num: int, **kw):
        super().__init__(parent, bg=BG_CARD, **kw)
        self.slot_num = slot_num

        # ── Top row: main settings ──────────────────────────────
        self._top = tk.Frame(self, bg=BG_CARD)
        self._top.pack(fill="x")

        # ── Enable checkbox ─────────────────────────────────────
        self.enabled_var = tk.BooleanVar(value=False)
        cb = tk.Checkbutton(self._top, variable=self.enabled_var,
                            bg=BG_CARD, fg=TEXT, selectcolor=BG_INPUT,
                            activebackground=BG_CARD, activeforeground=TEXT,
                            command=self._on_toggle)
        cb.pack(side="left", padx=(0, 4))

        # Slot label
        tk.Label(self._top, text=f"#{slot_num}", font=FONT_HEADING, bg=BG_CARD,
                 fg=ACCENT, width=3).pack(side="left", padx=(0, 6))

        # Symbol combo
        self.sym = LabelledCombo(self._top, "Symbol", SYMBOLS, "", width=14)
        self.sym.pack(side="left", padx=(0, 6))

        # Interval combo
        self.interval = LabelledCombo(self._top, "Timeframe", INTERVALS, "15m", width=6)
        self.interval.pack(side="left", padx=(0, 6))

        # Bind interval change to auto-fill SL/TP/Lev
        self.interval._combo.bind("<<ComboboxSelected>>", self._on_interval_change)

        # Strategy combo
        self.strategy = LabelledCombo(self._top, "Strategy", STRATEGIES,
                                       "ema_crossover", width=16)
        self.strategy.pack(side="left", padx=(0, 6))
        self.strategy._combo.bind("<<ComboboxSelected>>", self._on_strategy_change)

        # Size / SL / TP / Leverage
        self.size_usd = LabelledEntry(self._top, "Size$", "100", width=6)
        self.size_usd.pack(side="left", padx=(0, 4))
        self.sl = LabelledEntry(self._top, "SL%", "1.0", width=5)
        self.sl.pack(side="left", padx=(0, 4))
        self.tp = LabelledEntry(self._top, "TP%", "2.0", width=5)
        self.tp.pack(side="left", padx=(0, 4))
        self.lev = LabelledEntry(self._top, "Lev", "5", width=4)
        self.lev.pack(side="left", padx=(0, 4))

        # Style hint
        self._style_lbl = tk.Label(self._top, text="", font=FONT_TINY,
                                    bg=BG_CARD, fg=TEXT_DIM, width=10)
        self._style_lbl.pack(side="left", padx=(4, 0))

        # Trailing SL checkbox
        self.trailing_sl_var = tk.BooleanVar(value=False)
        self._trail_cb = tk.Checkbutton(
            self._top, text="Trail SL", variable=self.trailing_sl_var,
            font=FONT_TINY, bg=BG_CARD, fg=TEXT, selectcolor=BG_INPUT,
            activebackground=BG_CARD, activeforeground=TEXT,
        )
        self._trail_cb.pack(side="left", padx=(6, 0))

        # Multi-timeframe confirmation checkbox
        self.mtf_enabled_var = tk.BooleanVar(value=True)
        self._mtf_cb = tk.Checkbutton(
            self._top, text="MTF", variable=self.mtf_enabled_var,
            font=FONT_TINY, bg=BG_CARD, fg=TEXT, selectcolor=BG_INPUT,
            activebackground=BG_CARD, activeforeground=TEXT,
        )
        self._mtf_cb.pack(side="left", padx=(6, 0))

        # ADX regime filter checkbox
        self.regime_filter_var = tk.BooleanVar(value=False)
        self._regime_cb = tk.Checkbutton(
            self._top, text="ADX", variable=self.regime_filter_var,
            font=FONT_TINY, bg=BG_CARD, fg=TEXT, selectcolor=BG_INPUT,
            activebackground=BG_CARD, activeforeground=TEXT,
        )
        self._regime_cb.pack(side="left", padx=(6, 0))

        # ATR-based stops checkbox
        self.atr_stops_var = tk.BooleanVar(value=False)
        self._atr_cb = tk.Checkbutton(
            self._top, text="ATR-SL", variable=self.atr_stops_var,
            font=FONT_TINY, bg=BG_CARD, fg=TEXT, selectcolor=BG_INPUT,
            activebackground=BG_CARD, activeforeground=TEXT,
        )
        self._atr_cb.pack(side="left", padx=(6, 0))

        # Loss cooldown checkbox
        self.loss_cooldown_var = tk.BooleanVar(value=False)
        self._cd_cb = tk.Checkbutton(
            self._top, text="Cooldown", variable=self.loss_cooldown_var,
            font=FONT_TINY, bg=BG_CARD, fg=TEXT, selectcolor=BG_INPUT,
            activebackground=BG_CARD, activeforeground=TEXT,
        )
        self._cd_cb.pack(side="left", padx=(6, 0))

        # Volume confirmation checkbox
        self.volume_confirm_var = tk.BooleanVar(value=False)
        self._vol_cb = tk.Checkbutton(
            self._top, text="Vol", variable=self.volume_confirm_var,
            font=FONT_TINY, bg=BG_CARD, fg=TEXT, selectcolor=BG_INPUT,
            activebackground=BG_CARD, activeforeground=TEXT,
        )
        self._vol_cb.pack(side="left", padx=(6, 0))

        # RSI exhaustion guard checkbox
        self.rsi_guard_var = tk.BooleanVar(value=False)
        self._rsi_guard_cb = tk.Checkbutton(
            self._top, text="RSI Guard", variable=self.rsi_guard_var,
            font=FONT_TINY, bg=BG_CARD, fg=TEXT, selectcolor=BG_INPUT,
            activebackground=BG_CARD, activeforeground=TEXT,
        )
        self._rsi_guard_cb.pack(side="left", padx=(6, 0))

        # RSI Guard threshold inputs (inline next to checkbox)
        self._rsi_low_entry = LabelledEntry(self._top, "RSI Low", "30", width=4)
        self._rsi_low_entry.pack(side="left", padx=(6, 0))
        self._rsi_high_entry = LabelledEntry(self._top, "RSI High", "70", width=4)
        self._rsi_high_entry.pack(side="left", padx=(4, 0))

        # ── Bottom row: strategy parameters ─────────────────────
        self._param_frame = tk.Frame(self, bg=BG_CARD)
        self._param_frame.pack(fill="x", padx=(36, 0), pady=(2, 0))

        self._param_entries: dict[str, LabelledEntry] = {}
        self._build_param_fields(self.strategy.get())

        self._on_toggle()  # grey-out if disabled
        self._update_rsi_guard_visibility()

    # ── Strategy parameter fields ───────────────────────────────
    def _build_param_fields(self, strategy_name: str):
        """Build labelled entries for the selected strategy's parameters."""
        # Clear existing
        for w in self._param_frame.winfo_children():
            w.destroy()
        self._param_entries.clear()

        key = strategy_name.lower()
        defaults = STRATEGY_DEFAULTS.get(key, {})
        if not defaults:
            return

        tk.Label(self._param_frame, text="⚙", font=FONT_TINY,
                 bg=BG_CARD, fg=TEXT_DIM).pack(side="left", padx=(0, 4))

        for pname, default_val in defaults.items():
            label = _PARAM_LABELS.get(pname, pname)
            entry = LabelledEntry(self._param_frame, label,
                                   str(default_val), width=6)
            entry.pack(side="left", padx=(0, 8))
            self._param_entries[pname] = entry

    def _on_strategy_change(self, _event=None):
        """Rebuild parameter fields when strategy choice changes."""
        self._build_param_fields(self.strategy.get())
        self._update_rsi_guard_visibility()

    def _update_rsi_guard_visibility(self):
        """Show RSI Guard controls only for EMA crossover / breakout."""
        strat = self.strategy.get().lower()
        show = 'ema' in strat or 'crossover' in strat or 'breakout' in strat
        if show:
            self._rsi_guard_cb.pack(side="left", padx=(6, 0))
            self._rsi_low_entry.pack(side="left", padx=(6, 0))
            self._rsi_high_entry.pack(side="left", padx=(4, 0))
        else:
            self._rsi_guard_cb.pack_forget()
            self._rsi_low_entry.pack_forget()
            self._rsi_high_entry.pack_forget()

    # ── Helpers ─────────────────────────────────────────────────
    def _on_interval_change(self, _event=None):
        """Auto-fill SL/TP/leverage from timeframe defaults."""
        d = Config.get_timeframe_defaults(self.interval.get())
        self.sl.set(str(d['sl']))
        self.tp.set(str(d['tp']))
        self.lev.set(str(d['lev']))
        self._style_lbl.config(text=d['style'])

    def _on_toggle(self):
        state = self.enabled_var.get()
        color = TEXT if state else TEXT_DIM
        for w in (self.sym, self.interval, self.strategy, self.size_usd, self.sl, self.tp, self.lev):
            for child in w.winfo_children():
                try:
                    child.config(fg=color)
                except tk.TclError:
                    pass

    def get_strategy_params(self) -> dict:
        """Return current strategy parameter values as a dict."""
        params = {}
        for pname, entry in self._param_entries.items():
            raw = entry.get().strip()
            if raw:
                try:
                    params[pname] = float(raw)
                except ValueError:
                    pass
        return params

    def get_slot(self) -> dict:
        return {
            'slot': self.slot_num,
            'symbol': self.sym.get(),
            'interval': self.interval.get(),
            'strategy': self.strategy.get(),
            'size_usd': float(self.size_usd.get() or 100),
            'sl': float(self.sl.get() or 1),
            'tp': float(self.tp.get() or 2),
            'leverage': int(self.lev.get() or 5),
            'enabled': self.enabled_var.get(),
            'strategy_params': self.get_strategy_params(),
            'trailing_sl': self.trailing_sl_var.get(),
            'mtf_enabled': self.mtf_enabled_var.get(),
            'regime_filter': self.regime_filter_var.get(),
            'atr_stops': self.atr_stops_var.get(),
            'loss_cooldown': self.loss_cooldown_var.get(),
            'volume_confirm': self.volume_confirm_var.get(),
            'rsi_guard': self.rsi_guard_var.get(),
            'rsi_guard_low': float(self._rsi_low_entry.get() or 30),
            'rsi_guard_high': float(self._rsi_high_entry.get() or 70),
        }

    def load_slot(self, s: dict):
        self.enabled_var.set(s.get('enabled', False))
        self.sym.set(s.get('symbol', ''))
        self.interval.set(s.get('interval', '15m'))
        self.strategy.set(s.get('strategy', 'ema_crossover'))
        self.size_usd.set(str(s.get('size_usd', 100)))
        self.sl.set(str(s.get('sl', 1.0)))
        self.tp.set(str(s.get('tp', 2.0)))
        self.lev.set(str(s.get('leverage', 5)))
        self.trailing_sl_var.set(s.get('trailing_sl', False))
        self.mtf_enabled_var.set(s.get('mtf_enabled', True))
        self.regime_filter_var.set(s.get('regime_filter', False))
        self.atr_stops_var.set(s.get('atr_stops', False))
        self.loss_cooldown_var.set(s.get('loss_cooldown', False))
        self.volume_confirm_var.set(s.get('volume_confirm', False))
        self.rsi_guard_var.set(s.get('rsi_guard', False))
        self._rsi_low_entry.set(str(s.get('rsi_guard_low', 30)))
        self._rsi_high_entry.set(str(s.get('rsi_guard_high', 70)))
        d = Config.get_timeframe_defaults(s.get('interval', '15m'))
        self._style_lbl.config(text=d['style'])

        # Rebuild strategy param fields and fill saved values
        self._build_param_fields(s.get('strategy', 'ema_crossover'))
        saved_params = s.get('strategy_params', {})
        for pname, entry in self._param_entries.items():
            if pname in saved_params:
                entry.set(str(saved_params[pname]))

        self._on_toggle()
        self._update_rsi_guard_visibility()


class SettingsTab(tk.Frame):
    """Full configuration panel mirroring .env parameters."""

    def __init__(self, parent, on_save=None, **kw):
        super().__init__(parent, bg=BG_DARK, **kw)
        self._on_save = on_save

        # Scrollable canvas wrapper (vertical + horizontal)
        scroll_frame = tk.Frame(self, bg=BG_DARK)
        scroll_frame.pack(fill="both", expand=True)

        canvas = tk.Canvas(scroll_frame, bg=BG_DARK, highlightthickness=0)
        v_scrollbar = tk.Scrollbar(scroll_frame, orient="vertical", command=canvas.yview)
        h_scrollbar = tk.Scrollbar(self, orient="horizontal", command=canvas.xview)
        self._inner = tk.Frame(canvas, bg=BG_DARK)
        self._inner.bind("<Configure>",
                         lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self._inner, anchor="nw")
        canvas.configure(yscrollcommand=v_scrollbar.set,
                         xscrollcommand=h_scrollbar.set)
        v_scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        h_scrollbar.pack(side="bottom", fill="x")

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        def _on_shift_mousewheel(event):
            canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        canvas.bind_all("<Shift-MouseWheel>", _on_shift_mousewheel)

        self._canvas = canvas
        self._build_sections()

        # Ensure inner content is never narrower than its natural width
        self._inner.update_idletasks()
        min_w = self._inner.winfo_reqwidth()
        canvas.configure(width=min_w)

    def _build_sections(self):
        p = self._inner

        # ── Credentials ─────────────────────────────────────────
        cred = Card(p, title="Credentials")
        cred.pack(fill="x", padx=PAD_X, pady=PAD_Y)

        row = tk.Frame(cred, bg=BG_CARD)
        row.pack(fill="x", padx=CARD_PAD, pady=(4, CARD_PAD))
        self.inp_private_key = LabelledEntry(row, "Private Key", width=50)
        self.inp_private_key.pack(side="left", padx=(0, 12))
        self.inp_wallet = LabelledEntry(row, "Wallet Address", width=46)
        self.inp_wallet.pack(side="left")

        row2 = tk.Frame(cred, bg=BG_CARD)
        row2.pack(fill="x", padx=CARD_PAD, pady=(0, CARD_PAD))
        self.inp_network = LabelledCombo(row2, "Network",
                                          ["Testnet", "Mainnet"], "Testnet")
        self.inp_network.pack(side="left", padx=(0, 12))

        # ── Position Slots (1-5) ────────────────────────────────
        slots_card = Card(p, title="Position Slots  (up to 5 independent trades)")
        slots_card.pack(fill="x", padx=PAD_X, pady=PAD_Y)

        # Timeframe reference (compact)
        ref_frame = tk.Frame(slots_card, bg=BG_CARD)
        ref_frame.pack(fill="x", padx=CARD_PAD, pady=(0, 6))
        tk.Label(ref_frame, text="Defaults:  ", font=FONT_TINY,
                 bg=BG_CARD, fg=TEXT_DIM).pack(side="left")
        for iv, d in Config.TIMEFRAME_DEFAULTS.items():
            txt = f"{iv}\u2192SL{d['sl']}% TP{d['tp']}% {d['lev']}x"
            tk.Label(ref_frame, text=txt, font=FONT_TINY, bg=BG_CARD,
                     fg=TEXT_DIM).pack(side="left", padx=(0, 10))

        tk.Label(slots_card,
                 text="Changing the Timeframe auto-fills SL/TP/Leverage. You can override manually.",
                 font=FONT_TINY, bg=BG_CARD, fg=TEXT_DIM
                 ).pack(fill="x", padx=CARD_PAD, pady=(0, 6))

        # Separator
        tk.Frame(slots_card, bg=BORDER, height=1).pack(fill="x", padx=CARD_PAD, pady=4)

        self._slot_rows: list[_SlotRow] = []
        for i in range(1, Config.MAX_SLOTS + 1):
            if i > 1:
                tk.Frame(slots_card, bg=BORDER, height=1).pack(
                    fill="x", padx=CARD_PAD, pady=2)
            sr = _SlotRow(slots_card, i)
            sr.pack(fill="x", padx=CARD_PAD, pady=3)
            self._slot_rows.append(sr)

        # ── Global Trading Parameters ──────────────────────────
        trading = Card(p, title="Global Trading Parameters")
        trading.pack(fill="x", padx=PAD_X, pady=PAD_Y)

        trow = tk.Frame(trading, bg=BG_CARD)
        trow.pack(fill="x", padx=CARD_PAD, pady=(4, CARD_PAD))

        self.inp_loop = LabelledEntry(trow, "Loop Interval (sec)", "15",
                                       width=8)
        self.inp_loop.pack(side="left", padx=(0, 12))
        self.inp_max_loss = LabelledEntry(trow, "Max Daily Loss ($)", "500",
                                           width=10)
        self.inp_max_loss.pack(side="left")

        # ── Email Notifications ─────────────────────────────────
        email_card = Card(p, title="Email Notifications")
        email_card.pack(fill="x", padx=PAD_X, pady=PAD_Y)

        self.email_enabled_var = tk.BooleanVar(value=False)
        erow0 = tk.Frame(email_card, bg=BG_CARD)
        erow0.pack(fill="x", padx=CARD_PAD, pady=(4, 6))
        tk.Checkbutton(erow0, text="  Enable email notifications on every trade",
                       variable=self.email_enabled_var,
                       font=FONT_BODY, bg=BG_CARD, fg=TEXT,
                       selectcolor=BG_INPUT, activebackground=BG_CARD,
                       activeforeground=TEXT).pack(side="left")

        erow1 = tk.Frame(email_card, bg=BG_CARD)
        erow1.pack(fill="x", padx=CARD_PAD, pady=(0, 6))
        self.inp_smtp_server = LabelledEntry(erow1, "SMTP Server",
                                              "smtp.gmail.com", width=20)
        self.inp_smtp_server.pack(side="left", padx=(0, 12))
        self.inp_smtp_port = LabelledEntry(erow1, "Port", "587", width=6)
        self.inp_smtp_port.pack(side="left", padx=(0, 12))

        erow2 = tk.Frame(email_card, bg=BG_CARD)
        erow2.pack(fill="x", padx=CARD_PAD, pady=(0, 6))
        self.inp_email_sender = LabelledEntry(erow2, "Sender Email", width=30)
        self.inp_email_sender.pack(side="left", padx=(0, 12))
        self.inp_email_password = LabelledEntry(erow2, "App Password", width=24)
        self.inp_email_password.pack(side="left", padx=(0, 12))
        self.inp_email_recipient = LabelledEntry(erow2, "Recipient (opt)", width=30)
        self.inp_email_recipient.pack(side="left")

        erow3 = tk.Frame(email_card, bg=BG_CARD)
        erow3.pack(fill="x", padx=CARD_PAD, pady=(0, CARD_PAD))
        ActionButton(erow3, "\U0001f4e7  Send Test Email", color=ACCENT,
                     command=self._send_test_email).pack(side="left", padx=(0, 8))
        self._email_status = tk.Label(erow3, text="", font=FONT_SMALL,
                                       bg=BG_CARD, fg=TEXT_DIM)
        self._email_status.pack(side="left")

        tk.Label(email_card,
                 text="Gmail: use an App Password (not your main password). "
                      "Google Account \u2192 Security \u2192 App Passwords.",
                 font=FONT_TINY, bg=BG_CARD, fg=TEXT_DIM, wraplength=500,
                 justify="left").pack(fill="x", padx=CARD_PAD, pady=(0, CARD_PAD))

        # ── Telegram Notifications ──────────────────────────────
        tg_card = Card(p, title="Telegram Notifications")
        tg_card.pack(fill="x", padx=PAD_X, pady=PAD_Y)

        self.tg_enabled_var = tk.BooleanVar(value=False)
        tg_row0 = tk.Frame(tg_card, bg=BG_CARD)
        tg_row0.pack(fill="x", padx=CARD_PAD, pady=(4, 6))
        tk.Checkbutton(tg_row0, text="  Enable Telegram alerts on every trade",
                       variable=self.tg_enabled_var,
                       font=FONT_BODY, bg=BG_CARD, fg=TEXT,
                       selectcolor=BG_INPUT, activebackground=BG_CARD,
                       activeforeground=TEXT).pack(side="left")

        tg_row1 = tk.Frame(tg_card, bg=BG_CARD)
        tg_row1.pack(fill="x", padx=CARD_PAD, pady=(0, 6))
        self.inp_tg_token = LabelledEntry(tg_row1, "Bot Token", width=40)
        self.inp_tg_token.pack(side="left", padx=(0, 12))
        self.inp_tg_chat_id = LabelledEntry(tg_row1, "Chat ID", width=16)
        self.inp_tg_chat_id.pack(side="left")

        tg_row2 = tk.Frame(tg_card, bg=BG_CARD)
        tg_row2.pack(fill="x", padx=CARD_PAD, pady=(0, CARD_PAD))
        ActionButton(tg_row2, "\U0001f4e8  Send Test Message", color=ACCENT,
                     command=self._send_test_telegram).pack(side="left", padx=(0, 8))
        self._tg_status = tk.Label(tg_row2, text="", font=FONT_SMALL,
                                    bg=BG_CARD, fg=TEXT_DIM)
        self._tg_status.pack(side="left")

        tk.Label(tg_card,
                 text="Create a bot via @BotFather, get its token. "
                      "Get your chat ID via @userinfobot.",
                 font=FONT_TINY, bg=BG_CARD, fg=TEXT_DIM, wraplength=500,
                 justify="left").pack(fill="x", padx=CARD_PAD, pady=(0, CARD_PAD))

        # ── Save / Reset buttons ────────────────────────────────
        btn_row = tk.Frame(p, bg=BG_DARK)
        btn_row.pack(fill="x", padx=PAD_X, pady=PAD_Y)
        ActionButton(btn_row, "\U0001f4be  Apply & Save", color=GREEN,
                     command=self._save).pack(side="left", padx=(0, 8))
        ActionButton(btn_row, "\u21bb  Reset Defaults", color=BG_INPUT,
                     command=self._reset).pack(side="left")

    # ── Getters ─────────────────────────────────────────────────
    def get_config(self) -> dict:
        """Return current settings as a dict."""
        slots = [sr.get_slot() for sr in self._slot_rows]
        return {
            "PRIVATE_KEY": self.inp_private_key.get(),
            "WALLET_ADDRESS": self.inp_wallet.get(),
            "USE_TESTNET": self.inp_network.get() == "Testnet",
            "LOOP_INTERVAL_SEC": self.inp_loop.get(),
            "MAX_DAILY_LOSS_USD": self.inp_max_loss.get(),
            "SLOTS": slots,
            # Email
            "EMAIL_ENABLED": self.email_enabled_var.get(),
            "SMTP_SERVER": self.inp_smtp_server.get(),
            "SMTP_PORT": self.inp_smtp_port.get(),
            "EMAIL_SENDER": self.inp_email_sender.get(),
            "EMAIL_PASSWORD": self.inp_email_password.get(),
            "EMAIL_RECIPIENT": self.inp_email_recipient.get(),
            # Telegram
            "TELEGRAM_ENABLED": self.tg_enabled_var.get(),
            "TELEGRAM_BOT_TOKEN": self.inp_tg_token.get(),
            "TELEGRAM_CHAT_ID": self.inp_tg_chat_id.get(),
        }

    def load_config(self, cfg: dict):
        """Populate fields from a config dict."""
        self.inp_private_key.set(cfg.get("PRIVATE_KEY", ""))
        self.inp_wallet.set(cfg.get("WALLET_ADDRESS", ""))
        net = "Testnet" if cfg.get("USE_TESTNET", True) else "Mainnet"
        self.inp_network.set(net)
        self.inp_loop.set(str(cfg.get("LOOP_INTERVAL_SEC", "15")))
        self.inp_max_loss.set(str(cfg.get("MAX_DAILY_LOSS_USD", "500")))

        # Slots
        slots = cfg.get("SLOTS", [])
        for i, sr in enumerate(self._slot_rows):
            if i < len(slots):
                sr.load_slot(slots[i])
            else:
                sr.load_slot({})

        # Email
        self.email_enabled_var.set(cfg.get("EMAIL_ENABLED", False))
        self.inp_smtp_server.set(cfg.get("SMTP_SERVER", "smtp.gmail.com"))
        self.inp_smtp_port.set(str(cfg.get("SMTP_PORT", "587")))
        self.inp_email_sender.set(cfg.get("EMAIL_SENDER", ""))
        self.inp_email_password.set(cfg.get("EMAIL_PASSWORD", ""))
        self.inp_email_recipient.set(cfg.get("EMAIL_RECIPIENT", ""))

        # Telegram
        self.tg_enabled_var.set(cfg.get("TELEGRAM_ENABLED", False))
        self.inp_tg_token.set(cfg.get("TELEGRAM_BOT_TOKEN", ""))
        self.inp_tg_chat_id.set(cfg.get("TELEGRAM_CHAT_ID", ""))

    def _save(self):
        if self._on_save:
            self._on_save(self.get_config())

    def _reset(self):
        self.load_config({})

    def _send_test_email(self):
        """Send a test email using current settings."""
        from core.email_notifier import EmailNotifier
        n = EmailNotifier(
            smtp_server=self.inp_smtp_server.get(),
            smtp_port=int(self.inp_smtp_port.get() or 587),
            sender_email=self.inp_email_sender.get(),
            sender_password=self.inp_email_password.get(),
            recipient_email=self.inp_email_recipient.get() or self.inp_email_sender.get(),
            enabled=True,
        )
        ok, msg = n.send_test()
        if ok:
            self._email_status.config(text="\u2713 Test email sent \u2013 check your inbox!", fg=GREEN)
        else:
            self._email_status.config(text=f"\u2717 {msg}", fg=RED)

    def _send_test_telegram(self):
        """Send a test Telegram message using current settings."""
        from core.telegram_notifier import TelegramNotifier
        n = TelegramNotifier(
            bot_token=self.inp_tg_token.get(),
            chat_id=self.inp_tg_chat_id.get(),
            enabled=True,
        )
        ok, msg = n.send_test()
        if ok:
            self._tg_status.config(text="\u2713 Test message sent!", fg=GREEN)
        else:
            self._tg_status.config(text=f"\u2717 {msg}", fg=RED)
