"""Price chart widget using matplotlib embedded in tkinter."""
from __future__ import annotations
import tkinter as tk
from datetime import datetime
from typing import Optional

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

from gui.theme import *

# Matplotlib dark style
plt.rcParams.update({
    "figure.facecolor": BG_CARD,
    "axes.facecolor": BG_DARK,
    "axes.edgecolor": BORDER,
    "axes.labelcolor": TEXT_DIM,
    "xtick.color": TEXT_DIM,
    "ytick.color": TEXT_DIM,
    "grid.color": BORDER,
    "grid.alpha": 0.4,
    "text.color": TEXT,
    "font.family": "sans-serif",
    "font.size": 9,
})


class PriceChart(tk.Frame):
    """Candlestick-style price chart with EMA overlays and volume."""

    def __init__(self, parent, **kw):
        super().__init__(parent, bg=BG_CARD, **kw)

        self.fig = Figure(figsize=(9, 4.5), dpi=100)
        self.fig.subplots_adjust(left=0.07, right=0.97, top=0.93,
                                 bottom=0.12, hspace=0.05)

        # Price axis + volume axis (shared x)
        self.ax_price = self.fig.add_subplot(211)
        self.ax_vol = self.fig.add_subplot(212, sharex=self.ax_price)

        self._setup_axes()

        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        # Store last data for quick redraws
        self._last_df: Optional[pd.DataFrame] = None

    def _setup_axes(self):
        for ax in (self.ax_price, self.ax_vol):
            ax.set_facecolor(BG_DARK)
            ax.tick_params(colors=TEXT_DIM, labelsize=8)
            ax.grid(True, alpha=0.25)

        self.ax_price.set_ylabel("Price ($)", fontsize=9, color=TEXT_DIM)
        self.ax_price.tick_params(labelbottom=False)
        self.ax_vol.set_ylabel("Volume", fontsize=9, color=TEXT_DIM)

    def update_chart(self, df: pd.DataFrame, symbol: str = "",
                     ema_fast: int = 9, ema_slow: int = 21,
                     entry_price: float | None = None,
                     sl_price: float | None = None,
                     tp_price: float | None = None):
        """
        Redraw chart with new OHLCV data.

        Args:
            df: DataFrame with timestamp, open, high, low, close, volume
            symbol: Display name
            ema_fast / ema_slow: EMA periods for overlay
            entry_price: Horizontal line for position entry
            sl_price / tp_price: Stop-loss / take-profit lines
        """
        if df is None or df.empty:
            return

        self._last_df = df.copy()
        self.ax_price.cla()
        self.ax_vol.cla()
        self._setup_axes()

        ts = df["timestamp"]
        o, h, l, c = df["open"], df["high"], df["low"], df["close"]
        v = df["volume"]

        # ── Candlestick bars ────────────────────────────────────
        colors_body = [GREEN if ci >= oi else RED for ci, oi in zip(c, o)]
        x = range(len(df))

        # Wicks
        for i in x:
            colour = GREEN if c.iloc[i] >= o.iloc[i] else RED
            self.ax_price.plot([i, i], [l.iloc[i], h.iloc[i]],
                               color=colour, linewidth=0.8)
        # Bodies
        body_bottom = [min(oi, ci) for oi, ci in zip(o, c)]
        body_height = [abs(ci - oi) for oi, ci in zip(o, c)]
        self.ax_price.bar(x, body_height, bottom=body_bottom, width=0.6,
                          color=colors_body, edgecolor=colors_body, linewidth=0.5)

        # ── EMAs ────────────────────────────────────────────────
        if len(df) > ema_slow:
            ema_f = c.ewm(span=ema_fast, adjust=False).mean()
            ema_s = c.ewm(span=ema_slow, adjust=False).mean()
            self.ax_price.plot(x, ema_f, color=ACCENT, linewidth=1.2,
                               label=f"EMA {ema_fast}", alpha=0.9)
            self.ax_price.plot(x, ema_s, color=ORANGE, linewidth=1.2,
                               label=f"EMA {ema_slow}", alpha=0.9)

        # ── Horizontal lines (entry, SL, TP) ───────────────────
        if entry_price:
            self.ax_price.axhline(entry_price, color=ACCENT, linewidth=1,
                                   linestyle="--", alpha=0.7, label="Entry")
        if sl_price:
            self.ax_price.axhline(sl_price, color=RED, linewidth=1,
                                   linestyle=":", alpha=0.7, label="Stop Loss")
        if tp_price:
            self.ax_price.axhline(tp_price, color=GREEN, linewidth=1,
                                   linestyle=":", alpha=0.7, label="Take Profit")

        # ── Volume bars ─────────────────────────────────────────
        vol_colors = [GREEN if c.iloc[i] >= o.iloc[i] else RED for i in x]
        self.ax_vol.bar(x, v, width=0.6, color=vol_colors, alpha=0.5)

        # ── X-axis labels  (show every nth timestamp) ───────────
        n = max(1, len(df) // 10)
        tick_pos = list(range(0, len(df), n))
        tick_labels = [ts.iloc[i].strftime("%H:%M\n%m/%d") if hasattr(ts.iloc[i], 'strftime')
                       else str(ts.iloc[i])[-11:-3] for i in tick_pos]
        self.ax_vol.set_xticks(tick_pos)
        self.ax_vol.set_xticklabels(tick_labels, fontsize=7)

        # ── Title & legend ──────────────────────────────────────
        last_price = c.iloc[-1]
        change = ((c.iloc[-1] - c.iloc[-2]) / c.iloc[-2] * 100) if len(c) > 1 else 0
        chg_color = GREEN if change >= 0 else RED
        title = f"{symbol}   ${last_price:,.2f}   ({change:+.2f}%)"
        self.ax_price.set_title(title, fontsize=11, color=TEXT, loc="left",
                                 pad=8, fontweight="bold")
        self.ax_price.legend(loc="upper left", fontsize=7, framealpha=0.3,
                              labelcolor=TEXT_DIM)

        self.canvas.draw_idle()
