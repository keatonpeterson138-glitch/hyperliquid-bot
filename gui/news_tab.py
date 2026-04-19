"""News & Events tab – live feed with impact severity indicators."""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk
from datetime import datetime, timezone
from gui.theme import *
from gui.components import Card, ActionButton, StatBox


# Impact → colour mapping
_IMPACT_COLOURS = {
    1: TEXT_DIM,    # LOW
    2: YELLOW,      # MEDIUM
    3: ORANGE,      # HIGH
    4: RED,         # CRITICAL
}
_IMPACT_LABELS = {
    1: "LOW",
    2: "MEDIUM",
    3: "HIGH",
    4: "CRITICAL",
}
_SENTIMENT_COLOURS = {
    "bearish": RED,
    "bullish": GREEN,
    "neutral": TEXT_DIM,
}


class NewsTab(tk.Frame):
    """Live news feed with severity, sentiment, and filtering."""

    def __init__(self, parent, on_refresh=None, **kw):
        super().__init__(parent, bg=BG_DARK, **kw)
        self._on_refresh = on_refresh

        # ── Top bar: filter + stats ─────────────────────────────
        top = tk.Frame(self, bg=BG_DARK)
        top.pack(fill="x", padx=PAD_X, pady=(PAD_Y, 4))

        tk.Label(top, text="Min Impact:", font=FONT_SMALL,
                 bg=BG_DARK, fg=TEXT_DIM).pack(side="left")
        self._filter_var = tk.StringVar(value="ALL")
        filt = ttk.Combobox(top, textvariable=self._filter_var,
                            values=["ALL", "MEDIUM+", "HIGH+", "CRITICAL"],
                            width=12, state="readonly", font=FONT_MONO_SM)
        filt.pack(side="left", padx=(4, 16))
        filt.bind("<<ComboboxSelected>>", lambda e: self._apply_filter())

        ActionButton(top, "⟳  Refresh", color=BG_INPUT,
                     command=self._refresh).pack(side="left", padx=(0, 12))
        self._auto_var = tk.BooleanVar(value=True)
        tk.Checkbutton(top, text="Auto-scroll", variable=self._auto_var,
                       bg=BG_DARK, fg=TEXT_DIM, selectcolor=BG_INPUT,
                       activebackground=BG_DARK, activeforeground=TEXT,
                       font=FONT_SMALL).pack(side="left")

        # Sentiment summary on the right
        sent_frame = tk.Frame(top, bg=BG_DARK)
        sent_frame.pack(side="right")
        tk.Label(sent_frame, text="SENTIMENT BIAS", font=FONT_TINY,
                 bg=BG_DARK, fg=TEXT_DIM).pack(anchor="e")
        self.sentiment_label = tk.Label(sent_frame, text="NEUTRAL",
                                         font=(FONT_MONO, 14, "bold"),
                                         bg=BG_DARK, fg=TEXT_DIM)
        self.sentiment_label.pack(anchor="e")

        # ── Alert banner (shown for CRITICAL) ───────────────────
        self.alert_frame = tk.Frame(self, bg=RED)
        self.alert_label = tk.Label(self.alert_frame, text="",
                                     font=(FONT_FAMILY, 12, "bold"),
                                     bg=RED, fg=WHITE, wraplength=800,
                                     anchor="w", justify="left")
        self.alert_label.pack(fill="x", padx=12, pady=6)
        self.alert_dismiss = ActionButton(self.alert_frame, "Dismiss",
                                          color="#8b0000",
                                          command=self._dismiss_alert)
        self.alert_dismiss.pack(side="right", padx=12, pady=4)
        # Hidden by default
        self.alert_frame.pack_forget()

        # ── Stats row ───────────────────────────────────────────
        stats_card = Card(self, title="News Stats (24h)")
        stats_card.pack(fill="x", padx=PAD_X, pady=(4, PAD_Y))
        srow = tk.Frame(stats_card, bg=BG_CARD)
        srow.pack(fill="x", padx=CARD_PAD, pady=(4, CARD_PAD))
        self.stat_total = StatBox(srow, "Total Items", "0")
        self.stat_total.pack(side="left", expand=True, fill="x")
        self.stat_critical = StatBox(srow, "Critical", "0", RED)
        self.stat_critical.pack(side="left", expand=True, fill="x")
        self.stat_high = StatBox(srow, "High", "0", ORANGE)
        self.stat_high.pack(side="left", expand=True, fill="x")
        self.stat_bearish = StatBox(srow, "Bearish", "0", RED)
        self.stat_bearish.pack(side="left", expand=True, fill="x")
        self.stat_bullish = StatBox(srow, "Bullish", "0", GREEN)
        self.stat_bullish.pack(side="left", expand=True, fill="x")
        self.stat_sources = StatBox(srow, "Sources", "0")
        self.stat_sources.pack(side="left", expand=True, fill="x")

        # ── Scrollable news feed ────────────────────────────────
        feed_card = Card(self, title="Live News Feed")
        feed_card.pack(fill="both", expand=True, padx=PAD_X, pady=(0, PAD_Y))

        inner = tk.Frame(feed_card, bg=BG_CARD)
        inner.pack(fill="both", expand=True, padx=CARD_PAD,
                   pady=(4, CARD_PAD))

        self._text = tk.Text(inner, bg=BG_CARD, fg=TEXT, font=FONT_MONO_SM,
                             relief="flat", wrap="word", state="disabled",
                             insertbackground=TEXT, selectbackground=ACCENT,
                             highlightthickness=0, padx=8, pady=8)
        sb = tk.Scrollbar(inner, command=self._text.yview,
                          bg=BG_CARD, troughcolor=BG_DARK)
        self._text.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._text.pack(side="left", fill="both", expand=True)

        # Tags for impact levels
        self._text.tag_config("time", foreground=TEXT_DIM)
        self._text.tag_config("source", foreground=ACCENT)
        self._text.tag_config("low", foreground=TEXT_DIM)
        self._text.tag_config("medium", foreground=YELLOW)
        self._text.tag_config("high", foreground=ORANGE)
        self._text.tag_config("critical", foreground=RED, font=(FONT_MONO, 10, "bold"))
        self._text.tag_config("bearish", foreground=RED)
        self._text.tag_config("bullish", foreground=GREEN)
        self._text.tag_config("neutral", foreground=TEXT_DIM)
        self._text.tag_config("separator", foreground=BORDER)

        # Internal store for filtering
        self._all_items: list[dict] = []

    # ── Public methods ──────────────────────────────────────────
    def add_news_item(self, headline: str, source: str, published: str,
                      impact: int, sentiment: str, url: str = "",
                      matched_keywords: list | None = None):
        """Add a single news item to the feed."""
        item = {
            "headline": headline,
            "source": source,
            "published": published,
            "impact": impact,
            "sentiment": sentiment,
            "url": url,
            "keywords": matched_keywords or [],
        }
        self._all_items.insert(0, item)
        # Cap
        if len(self._all_items) > 500:
            self._all_items = self._all_items[:500]

        # Check if passes current filter
        if self._passes_filter(item):
            self._render_item(item)

        # Show alert banner for CRITICAL
        if impact >= 4:
            self._show_alert(headline, source, sentiment)

    def update_stats(self, total: int, critical: int, high: int,
                     bearish: int, bullish: int, sources: int):
        self.stat_total.set(str(total))
        self.stat_critical.set(str(critical), RED if critical > 0 else TEXT_DIM)
        self.stat_high.set(str(high), ORANGE if high > 0 else TEXT_DIM)
        self.stat_bearish.set(str(bearish), RED if bearish > 0 else TEXT_DIM)
        self.stat_bullish.set(str(bullish), GREEN if bullish > 0 else TEXT_DIM)
        self.stat_sources.set(str(sources))

    def update_sentiment(self, bias: str):
        """Update the sentiment bias label."""
        colour = _SENTIMENT_COLOURS.get(bias, TEXT_DIM)
        self.sentiment_label.config(text=bias.upper(), fg=colour)

    def clear(self):
        self._all_items.clear()
        self._text.config(state="normal")
        self._text.delete("1.0", "end")
        self._text.config(state="disabled")

    # ── Internal ────────────────────────────────────────────────
    def _render_item(self, item: dict):
        """Append a formatted news item to the text widget."""
        self._text.config(state="normal")

        impact_val = item["impact"]
        impact_tag = _IMPACT_LABELS.get(impact_val, "LOW").lower()
        sent_tag = item["sentiment"]
        impact_name = _IMPACT_LABELS.get(impact_val, "LOW")

        # Separator
        self._text.insert("end", "─" * 80 + "\n", "separator")

        # Time + impact badge
        self._text.insert("end", f"[{item['published']}] ", "time")
        self._text.insert("end", f"[{impact_name}] ", impact_tag)
        self._text.insert("end", f"[{item['sentiment'].upper()}] ", sent_tag)
        self._text.insert("end", f"({item['source']})\n", "source")

        # Headline
        self._text.insert("end", f"  {item['headline']}\n", impact_tag)

        # Keywords if any
        if item.get("keywords"):
            kw_str = ", ".join(item["keywords"][:3])
            self._text.insert("end", f"  Triggers: {kw_str}\n", "time")

        if self._auto_var.get():
            self._text.see("1.0")  # scroll to top (newest)

        self._text.config(state="disabled")

    def _passes_filter(self, item: dict) -> bool:
        filt = self._filter_var.get()
        if filt == "ALL":
            return True
        if filt == "MEDIUM+" and item["impact"] >= 2:
            return True
        if filt == "HIGH+" and item["impact"] >= 3:
            return True
        if filt == "CRITICAL" and item["impact"] >= 4:
            return True
        return False

    def _apply_filter(self):
        """Re-render all items with current filter."""
        self._text.config(state="normal")
        self._text.delete("1.0", "end")
        self._text.config(state="disabled")

        for item in reversed(self._all_items):  # oldest first so newest on top
            if self._passes_filter(item):
                self._render_item(item)

    def _show_alert(self, headline: str, source: str, sentiment: str):
        """Show the red alert banner for critical events."""
        emoji = "🔴" if sentiment == "bearish" else "🟡"
        self.alert_label.config(
            text=f"{emoji} CRITICAL ALERT — {source}: {headline}"
        )
        self.alert_frame.pack(fill="x", padx=PAD_X, pady=(0, 4),
                              after=self.winfo_children()[0])  # after top bar

    def _dismiss_alert(self):
        self.alert_frame.pack_forget()

    def _refresh(self):
        if self._on_refresh:
            self._on_refresh()
