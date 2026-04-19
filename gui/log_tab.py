"""Trade log tab – scrollable log + trade history table."""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk
from gui.theme import *
from gui.components import Card, ScrollableLog, ActionButton


class TradeLogTab(tk.Frame):
    """Tab showing live activity log and trade history table."""

    def __init__(self, parent, **kw):
        super().__init__(parent, bg=BG_DARK, **kw)

        # ── Live activity log ───────────────────────────────────
        log_card = Card(self, title="Live Activity Log")
        log_card.pack(fill="both", expand=True, padx=PAD_X, pady=PAD_Y)

        btn_row = tk.Frame(log_card, bg=BG_CARD)
        btn_row.pack(fill="x", padx=CARD_PAD, pady=(0, 4))
        ActionButton(btn_row, "Clear Log", color=BG_INPUT,
                     command=self._clear_log).pack(side="right")

        self.log = ScrollableLog(log_card)
        self.log.pack(fill="both", expand=True, padx=CARD_PAD,
                      pady=(0, CARD_PAD))

        # ── Trade history table ─────────────────────────────────
        history_card = Card(self, title="Trade History")
        history_card.pack(fill="x", padx=PAD_X, pady=(0, PAD_Y))

        columns = ("time", "symbol", "side", "size", "price", "pnl", "reason")
        style = ttk.Style()
        style.configure("Dark.Treeview",
                         background=BG_DARK, foreground=TEXT,
                         fieldbackground=BG_DARK, borderwidth=0,
                         font=FONT_MONO_SM, rowheight=28)
        style.configure("Dark.Treeview.Heading",
                         background=BG_INPUT, foreground=TEXT_DIM,
                         font=(FONT_FAMILY, 9, "bold"), borderwidth=0,
                         relief="flat")
        style.map("Dark.Treeview",
                  background=[("selected", BG_INPUT)],
                  foreground=[("selected", ACCENT)])

        self.tree = ttk.Treeview(history_card, columns=columns,
                                 show="headings", height=6,
                                 style="Dark.Treeview")
        self.tree.pack(fill="x", padx=CARD_PAD, pady=(4, CARD_PAD))

        headings = {
            "time": ("Time", 140),
            "symbol": ("Symbol", 100),
            "side": ("Side", 70),
            "size": ("Size", 90),
            "price": ("Price", 110),
            "pnl": ("P&L", 100),
            "reason": ("Reason", 220),
        }
        for col, (text, width) in headings.items():
            self.tree.heading(col, text=text, anchor="w")
            self.tree.column(col, width=width, anchor="w")

    def _clear_log(self):
        self.log.clear()

    def add_trade(self, time: str, symbol: str, side: str, size: str,
                  price: str, pnl: str, reason: str):
        """Insert a trade row at the top of the history table."""
        self.tree.insert("", 0, values=(time, symbol, side, size,
                                         price, pnl, reason))
        # Keep max 200 rows
        children = self.tree.get_children()
        if len(children) > 200:
            self.tree.delete(children[-1])
