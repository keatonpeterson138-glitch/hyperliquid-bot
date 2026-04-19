"""Main dashboard tab – price chart + current market info + controls."""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk
from gui.theme import *
from gui.components import Card, StatBox, ActionButton
from gui.chart_widget import PriceChart


class DashboardTab(tk.Frame):
    """Central dashboard view with chart, market stats, and bot controls."""

    def __init__(self, parent, on_start=None, on_stop=None,
                 on_close_position=None, **kw):
        super().__init__(parent, bg=BG_DARK, **kw)

        # ── Top control bar ─────────────────────────────────────
        controls = tk.Frame(self, bg=BG_DARK)
        controls.pack(fill="x", padx=PAD_X, pady=(PAD_Y, 4))

        self.btn_start = ActionButton(controls, "▶  Start Bot",
                                      color=GREEN, command=on_start)
        self.btn_start.pack(side="left", padx=(0, 6))
        self.btn_stop = ActionButton(controls, "■  Stop Bot",
                                     color=RED, command=on_stop)
        self.btn_stop.pack(side="left", padx=(0, 6))
        self.btn_stop.config(state="disabled")
        self.btn_close = ActionButton(controls, "✕  Close Position",
                                      color=BG_INPUT, command=on_close_position)
        self.btn_close.pack(side="left", padx=(0, 6))

        # Live price display on the right
        price_frame = tk.Frame(controls, bg=BG_DARK)
        price_frame.pack(side="right")
        tk.Label(price_frame, text="MARK PRICE", font=FONT_TINY,
                 bg=BG_DARK, fg=TEXT_DIM).pack(anchor="e")
        self.live_price = tk.Label(price_frame, text="$0.00",
                                   font=(FONT_MONO, 22, "bold"),
                                   bg=BG_DARK, fg=TEXT)
        self.live_price.pack(anchor="e")

        # ── Price chart ─────────────────────────────────────────
        self.chart = PriceChart(self)
        self.chart.pack(fill="both", expand=True, padx=PAD_X, pady=PAD_Y)

        # ── Market stats table (multi-row) ────────────────────────
        stats_frame = Card(self, title="Market Info")
        stats_frame.pack(fill="x", padx=PAD_X, pady=(0, PAD_Y))

        columns = ("symbol", "price", "24h_vol", "funding", "oi", "24h_chg", "leverage")
        col_headings = {
            "symbol": "SYMBOL",
            "price": "MARK PRICE",
            "24h_vol": "24H VOLUME",
            "funding": "FUNDING RATE",
            "oi": "OPEN INTEREST",
            "24h_chg": "24H CHANGE",
            "leverage": "LEVERAGE",
        }

        style = ttk.Style()
        style.configure("Market.Treeview",
                        background=BG_CARD,
                        foreground=TEXT,
                        fieldbackground=BG_CARD,
                        borderwidth=0,
                        font=FONT_MONO_SM,
                        rowheight=28)
        style.configure("Market.Treeview.Heading",
                        background=BG_CARD,
                        foreground=TEXT_DIM,
                        borderwidth=0,
                        font=FONT_TINY,
                        relief="flat")
        style.map("Market.Treeview",
                  background=[("selected", BG_INPUT)],
                  foreground=[("selected", ACCENT)])
        style.map("Market.Treeview.Heading",
                  background=[("active", BG_CARD)])

        self.market_tree = ttk.Treeview(
            stats_frame, columns=columns, show="headings",
            style="Market.Treeview", height=5,
        )
        for col in columns:
            anchor = "w" if col == "symbol" else "e"
            width = 110 if col == "symbol" else 130
            self.market_tree.heading(col, text=col_headings[col], anchor=anchor)
            self.market_tree.column(col, width=width, anchor=anchor, stretch=True)

        self.market_tree.tag_configure("pos_chg", foreground=GREEN)
        self.market_tree.tag_configure("neg_chg", foreground=RED)
        self.market_tree.pack(fill="x", padx=CARD_PAD, pady=(4, CARD_PAD))

        # Track inserted iids keyed by symbol
        self._market_rows: dict[str, str] = {}

    # ── Public update methods ───────────────────────────────────
    def set_running(self, running: bool):
        if running:
            self.btn_start.config(state="disabled")
            self.btn_stop.config(state="normal")
        else:
            self.btn_start.config(state="normal")
            self.btn_stop.config(state="disabled")

    def update_price(self, price: float, prev_price: float | None = None):
        color = TEXT
        if prev_price:
            color = GREEN if price >= prev_price else RED
        self.live_price.config(text=f"${price:,.2f}", fg=color)

    def update_market_stats(self, symbol: str, volume: str, funding: str,
                            oi: str, change_24h: str, leverage: str,
                            price: str = "--"):
        """Insert or update one row in the market-info table."""
        tag = ()
        if change_24h != "--":
            try:
                val = float(change_24h.replace("%", "").replace("+", ""))
                tag = ("pos_chg",) if val >= 0 else ("neg_chg",)
            except ValueError:
                pass

        values = (symbol, price, volume, funding, oi, change_24h, leverage)

        if symbol in self._market_rows:
            iid = self._market_rows[symbol]
            self.market_tree.item(iid, values=values, tags=tag)
        else:
            iid = self.market_tree.insert("", "end", values=values, tags=tag)
            self._market_rows[symbol] = iid

    def clear_market_stats(self):
        """Remove all rows from the market-info table."""
        for iid in self._market_rows.values():
            self.market_tree.delete(iid)
        self._market_rows.clear()
