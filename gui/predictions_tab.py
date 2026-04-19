"""Predictions tab – HIP-4 outcome market viewer, arb scanner & position tracker."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from datetime import datetime, timezone
from typing import Optional

from gui.theme import *
from gui.components import Card, ActionButton, StatBox


# Edge colour mapping
def _edge_color(edge: float) -> str:
    """Return a colour for an edge value."""
    if abs(edge) >= 0.10:
        return GREEN if edge > 0 else RED
    if abs(edge) >= 0.03:
        return YELLOW
    return TEXT_DIM


class PredictionsTab(tk.Frame):
    """HIP-4 Prediction Markets — outcome viewer, arb scanner, position tracker.

    Layout:
        ┌─ Top bar ─────────────────────────────────────────────────────────┐
        │ [🔍 Scan]  [▶ Auto-Scan ON/OFF]  Min Edge [___]  Vol [___]       │
        └────────────────────────────────────────────────────────────────────┘
        ┌─ Controls bar ────────────────────────────────────────────────────┐
        │ [⚡ Auto-Execute]  Strength [___] Kelly [___] Max Pos [__]       │
        │ Max Exposure [___]  [IOC]                                         │
        └────────────────────────────────────────────────────────────────────┘
        ┌─ Stats Row ───────────────────────────────────────────────────────┐
        │ Outcomes | Opportunities | Avg Edge | Positions | Exposure | P&L  │
        └────────────────────────────────────────────────────────────────────┘
        ┌─ Outcomes Table (Treeview) ───────────────────────────────────────┐
        │ Coin | Underlying | Expiry | Strike | Side | Theo | Market | Edge│
        └────────────────────────────────────────────────────────────────────┘
        ┌─ Positions Table (Treeview) ──────────────────────────────────────┐
        │ Coin | Side | Size | Entry | Current | Edge | P&L | Action       │
        └────────────────────────────────────────────────────────────────────┘
        ┌─ Activity Log ────────────────────────────────────────────────────┐
        │ Scrollable text log of arb events and trades                      │
        └────────────────────────────────────────────────────────────────────┘
    """

    def __init__(self, parent, on_scan=None, on_execute=None,
                 on_close_position=None, on_toggle_auto=None,
                 on_toggle_auto_exec=None, **kw):
        super().__init__(parent, bg=BG_DARK, **kw)
        self._on_scan = on_scan
        self._on_execute = on_execute
        self._on_close_position = on_close_position
        self._on_toggle_auto = on_toggle_auto
        self._on_toggle_auto_exec = on_toggle_auto_exec

        self._build_top_bar()
        self._build_controls_bar()
        self._build_stats_row()
        self._build_outcomes_table()
        self._build_positions_table()
        self._build_log()

    # ──────────────────────────────────────────────────────────────
    # Build methods
    # ──────────────────────────────────────────────────────────────
    def _build_top_bar(self):
        top = tk.Frame(self, bg=BG_DARK)
        top.pack(fill="x", padx=PAD_X, pady=(PAD_Y, 4))

        ActionButton(top, "🔍  Scan", color=ACCENT,
                     command=self._do_scan).pack(side="left", padx=(0, 8))

        self._auto_var = tk.BooleanVar(value=False)
        tk.Checkbutton(top, text="Auto-Scan (60s)", variable=self._auto_var,
                       bg=BG_DARK, fg=TEXT_DIM, selectcolor=BG_INPUT,
                       activebackground=BG_DARK, activeforeground=TEXT,
                       font=FONT_SMALL,
                       command=self._toggle_auto).pack(side="left", padx=(0, 20))

        tk.Label(top, text="Min Edge:", font=FONT_SMALL,
                 bg=BG_DARK, fg=TEXT_DIM).pack(side="left")
        self._min_edge_var = tk.StringVar(value="0.03")
        edge_entry = tk.Entry(top, textvariable=self._min_edge_var,
                              width=6, font=FONT_MONO_SM,
                              bg=BG_INPUT, fg=TEXT,
                              insertbackground=TEXT, relief="flat",
                              highlightthickness=0)
        edge_entry.pack(side="left", padx=(4, 16))

        tk.Label(top, text="Vol Override:", font=FONT_SMALL,
                 bg=BG_DARK, fg=TEXT_DIM).pack(side="left")
        self._vol_var = tk.StringVar(value="auto")
        vol_entry = tk.Entry(top, textvariable=self._vol_var,
                             width=6, font=FONT_MONO_SM,
                             bg=BG_INPUT, fg=TEXT,
                             insertbackground=TEXT, relief="flat",
                             highlightthickness=0)
        vol_entry.pack(side="left", padx=(4, 16))

        # Status label on the right
        self._status_label = tk.Label(top, text="Idle", font=FONT_SMALL,
                                       bg=BG_DARK, fg=TEXT_DIM)
        self._status_label.pack(side="right")

    def _build_controls_bar(self):
        """Second row — auto-execute toggle and selectiveness controls."""
        ctl = tk.Frame(self, bg=BG_DARK)
        ctl.pack(fill="x", padx=PAD_X, pady=(0, 4))

        # Auto-Execute toggle
        self._auto_exec_var = tk.BooleanVar(value=False)
        tk.Checkbutton(ctl, text="⚡ Auto-Execute", variable=self._auto_exec_var,
                       bg=BG_DARK, fg=YELLOW, selectcolor=BG_INPUT,
                       activebackground=BG_DARK, activeforeground=YELLOW,
                       font=FONT_SMALL,
                       command=self._toggle_auto_exec).pack(side="left", padx=(0, 20))

        # Min Strength
        tk.Label(ctl, text="Min Strength:", font=FONT_SMALL,
                 bg=BG_DARK, fg=TEXT_DIM).pack(side="left")
        self._min_strength_var = tk.StringVar(value="0.30")
        tk.Entry(ctl, textvariable=self._min_strength_var,
                 width=5, font=FONT_MONO_SM,
                 bg=BG_INPUT, fg=TEXT,
                 insertbackground=TEXT, relief="flat",
                 highlightthickness=0).pack(side="left", padx=(4, 12))

        # Kelly Fraction
        tk.Label(ctl, text="Kelly %:", font=FONT_SMALL,
                 bg=BG_DARK, fg=TEXT_DIM).pack(side="left")
        self._kelly_var = tk.StringVar(value="0.25")
        tk.Entry(ctl, textvariable=self._kelly_var,
                 width=5, font=FONT_MONO_SM,
                 bg=BG_INPUT, fg=TEXT,
                 insertbackground=TEXT, relief="flat",
                 highlightthickness=0).pack(side="left", padx=(4, 12))

        # Max Positions
        tk.Label(ctl, text="Max Pos:", font=FONT_SMALL,
                 bg=BG_DARK, fg=TEXT_DIM).pack(side="left")
        self._max_pos_var = tk.StringVar(value="5")
        tk.Entry(ctl, textvariable=self._max_pos_var,
                 width=4, font=FONT_MONO_SM,
                 bg=BG_INPUT, fg=TEXT,
                 insertbackground=TEXT, relief="flat",
                 highlightthickness=0).pack(side="left", padx=(4, 12))

        # Max Exposure
        tk.Label(ctl, text="Max Exposure:", font=FONT_SMALL,
                 bg=BG_DARK, fg=TEXT_DIM).pack(side="left")
        self._max_exposure_var = tk.StringVar(value="100")
        tk.Entry(ctl, textvariable=self._max_exposure_var,
                 width=6, font=FONT_MONO_SM,
                 bg=BG_INPUT, fg=TEXT,
                 insertbackground=TEXT, relief="flat",
                 highlightthickness=0).pack(side="left", padx=(4, 12))

        # Use IOC toggle
        self._ioc_var = tk.BooleanVar(value=False)
        tk.Checkbutton(ctl, text="IOC (market)", variable=self._ioc_var,
                       bg=BG_DARK, fg=TEXT_DIM, selectcolor=BG_INPUT,
                       activebackground=BG_DARK, activeforeground=TEXT,
                       font=FONT_SMALL).pack(side="left", padx=(8, 0))

        # Exec status on the right
        self._exec_status = tk.Label(ctl, text="Exec: OFF", font=FONT_SMALL,
                                      bg=BG_DARK, fg=TEXT_DIM)
        self._exec_status.pack(side="right")

    def _build_stats_row(self):
        stats_card = Card(self, title="Prediction Markets Overview")
        stats_card.pack(fill="x", padx=PAD_X, pady=(4, PAD_Y))

        srow = tk.Frame(stats_card, bg=BG_CARD)
        srow.pack(fill="x", padx=CARD_PAD, pady=(4, CARD_PAD))

        self.stat_outcomes = StatBox(srow, "Outcomes", "0")
        self.stat_outcomes.pack(side="left", expand=True, fill="x")
        self.stat_opportunities = StatBox(srow, "Opportunities", "0", ACCENT)
        self.stat_opportunities.pack(side="left", expand=True, fill="x")
        self.stat_avg_edge = StatBox(srow, "Avg Edge", "--")
        self.stat_avg_edge.pack(side="left", expand=True, fill="x")
        self.stat_positions = StatBox(srow, "Positions", "0")
        self.stat_positions.pack(side="left", expand=True, fill="x")
        self.stat_exposure = StatBox(srow, "Exposure", "0")
        self.stat_exposure.pack(side="left", expand=True, fill="x")
        self.stat_pnl = StatBox(srow, "Session P&L", "$0.00")
        self.stat_pnl.pack(side="left", expand=True, fill="x")

    def _build_outcomes_table(self):
        """Outcomes table — all price-binary outcomes with pricing."""
        table_card = Card(self, title="Outcome Markets")
        table_card.pack(fill="both", expand=True,
                        padx=PAD_X, pady=(0, PAD_Y))

        # Treeview style
        style = ttk.Style()
        style.configure("Pred.Treeview",
                        background=BG_CARD,
                        foreground=TEXT,
                        fieldbackground=BG_CARD,
                        borderwidth=0,
                        font=FONT_MONO_SM,
                        rowheight=26)
        style.configure("Pred.Treeview.Heading",
                        background=BG_CARD,
                        foreground=TEXT_DIM,
                        borderwidth=0,
                        font=FONT_TINY,
                        relief="flat")
        style.map("Pred.Treeview",
                  background=[("selected", BG_INPUT)],
                  foreground=[("selected", ACCENT)])
        style.map("Pred.Treeview.Heading",
                  background=[("active", BG_CARD)])

        columns = ("coin", "underlying", "expiry", "strike", "side",
                   "theo", "market", "edge", "iv", "signal")
        col_headings = {
            "coin": "COIN",
            "underlying": "UNDERLYING",
            "expiry": "EXPIRY",
            "strike": "STRIKE",
            "side": "SIDE",
            "theo": "THEO",
            "market": "MARKET",
            "edge": "EDGE",
            "iv": "IV",
            "signal": "SIGNAL",
        }
        col_widths = {
            "coin": 80, "underlying": 70, "expiry": 100, "strike": 90,
            "side": 50, "theo": 75, "market": 75, "edge": 80, "iv": 65,
            "signal": 80,
        }

        tree_frame = tk.Frame(table_card, bg=BG_CARD)
        tree_frame.pack(fill="both", expand=True, padx=CARD_PAD,
                        pady=(4, CARD_PAD))

        self.outcomes_tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings",
            style="Pred.Treeview", height=8,
        )
        for col in columns:
            anchor = "w" if col in ("coin", "underlying", "signal") else "e"
            self.outcomes_tree.heading(col, text=col_headings[col],
                                       anchor=anchor)
            self.outcomes_tree.column(col, width=col_widths.get(col, 80),
                                      anchor=anchor, stretch=True)

        # Tags for edge colouring
        self.outcomes_tree.tag_configure("edge_pos", foreground=GREEN)
        self.outcomes_tree.tag_configure("edge_neg", foreground=RED)
        self.outcomes_tree.tag_configure("edge_small", foreground=YELLOW)
        self.outcomes_tree.tag_configure("edge_none", foreground=TEXT_DIM)

        sb = ttk.Scrollbar(tree_frame, orient="vertical",
                           command=self.outcomes_tree.yview)
        self.outcomes_tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.outcomes_tree.pack(side="left", fill="both", expand=True)

        # Track rows by coin
        self._outcome_rows: dict[str, str] = {}

    def _build_positions_table(self):
        """Positions table — open arb positions."""
        pos_card = Card(self, title="Arb Positions")
        pos_card.pack(fill="x", padx=PAD_X, pady=(0, PAD_Y))

        columns = ("coin", "side_label", "direction", "size",
                   "entry", "current", "edge", "pnl")
        col_headings = {
            "coin": "COIN",
            "side_label": "YES/NO",
            "direction": "DIR",
            "size": "SIZE",
            "entry": "ENTRY",
            "current": "CURRENT",
            "edge": "ENTRY EDGE",
            "pnl": "P&L",
        }
        col_widths = {
            "coin": 80, "side_label": 60, "direction": 50, "size": 60,
            "entry": 80, "current": 80, "edge": 80, "pnl": 80,
        }

        tree_frame = tk.Frame(pos_card, bg=BG_CARD)
        tree_frame.pack(fill="x", padx=CARD_PAD, pady=(4, CARD_PAD))

        self.positions_tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings",
            style="Pred.Treeview", height=4,
        )
        for col in columns:
            anchor = "w" if col in ("coin", "side_label", "direction") else "e"
            self.positions_tree.heading(col, text=col_headings[col],
                                        anchor=anchor)
            self.positions_tree.column(col, width=col_widths.get(col, 70),
                                       anchor=anchor, stretch=True)

        self.positions_tree.tag_configure("profit", foreground=GREEN)
        self.positions_tree.tag_configure("loss", foreground=RED)
        self.positions_tree.pack(fill="x")

        # Close selected position button
        btn_frame = tk.Frame(pos_card, bg=BG_CARD)
        btn_frame.pack(fill="x", padx=CARD_PAD, pady=(0, CARD_PAD))
        ActionButton(btn_frame, "Close Selected", color=RED,
                     command=self._close_selected).pack(side="right")

        self._position_rows: dict[str, str] = {}

    def _build_log(self):
        """Activity log for arb events."""
        log_card = Card(self, title="Arb Activity")
        log_card.pack(fill="x", padx=PAD_X, pady=(0, PAD_Y))

        inner = tk.Frame(log_card, bg=BG_CARD)
        inner.pack(fill="x", padx=CARD_PAD, pady=(4, CARD_PAD))

        self._log_text = tk.Text(inner, bg=BG_CARD, fg=TEXT,
                                  font=FONT_MONO_SM, relief="flat",
                                  wrap="word", state="disabled",
                                  height=6, insertbackground=TEXT,
                                  selectbackground=ACCENT,
                                  highlightthickness=0, padx=8, pady=8)
        sb = tk.Scrollbar(inner, command=self._log_text.yview,
                          bg=BG_CARD, troughcolor=BG_DARK)
        self._log_text.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._log_text.pack(side="left", fill="both", expand=True)

        self._log_text.tag_config("time", foreground=TEXT_DIM)
        self._log_text.tag_config("buy", foreground=GREEN)
        self._log_text.tag_config("sell", foreground=RED)
        self._log_text.tag_config("close", foreground=YELLOW)
        self._log_text.tag_config("info", foreground=ACCENT)
        self._log_text.tag_config("warn", foreground=ORANGE)
        self._log_text.tag_config("scan", foreground=TEXT_DIM)

    # ──────────────────────────────────────────────────────────────
    # Public update methods  (called from main thread via root.after)
    # ──────────────────────────────────────────────────────────────

    def update_outcome(self, coin: str, underlying: str, expiry: str,
                       strike: str, side: str, theo: str, market: str,
                       edge: float, iv: str, signal: str):
        """Insert or update one row in the outcomes table."""
        # Determine tag from edge
        abs_e = abs(edge)
        if abs_e >= 0.10:
            tag = "edge_pos" if edge > 0 else "edge_neg"
        elif abs_e >= 0.03:
            tag = "edge_small"
        else:
            tag = "edge_none"

        edge_str = f"{edge:+.4f}" if edge != 0 else "--"
        values = (coin, underlying, expiry, strike, side,
                  theo, market, edge_str, iv, signal)

        iid = self._outcome_rows.get(coin)
        if iid:
            self.outcomes_tree.item(iid, values=values, tags=(tag,))
        else:
            iid = self.outcomes_tree.insert("", "end", values=values,
                                             tags=(tag,))
            self._outcome_rows[coin] = iid

    def clear_outcomes(self):
        """Remove all rows from the outcomes table."""
        for iid in self._outcome_rows.values():
            self.outcomes_tree.delete(iid)
        self._outcome_rows.clear()

    def update_position(self, coin: str, side_label: str, direction: str,
                        size: str, entry: str, current: str, edge: str,
                        pnl: float):
        """Insert or update one row in the positions table."""
        tag = "profit" if pnl >= 0 else "loss"
        pnl_str = f"${pnl:+.4f}"
        values = (coin, side_label, direction, size, entry, current,
                  edge, pnl_str)

        iid = self._position_rows.get(coin)
        if iid:
            self.positions_tree.item(iid, values=values, tags=(tag,))
        else:
            iid = self.positions_tree.insert("", "end", values=values,
                                              tags=(tag,))
            self._position_rows[coin] = iid

    def remove_position(self, coin: str):
        """Remove a position row."""
        iid = self._position_rows.pop(coin, None)
        if iid:
            self.positions_tree.delete(iid)

    def clear_positions(self):
        """Remove all position rows."""
        for iid in self._position_rows.values():
            self.positions_tree.delete(iid)
        self._position_rows.clear()

    def update_stats(self, outcomes: int, opportunities: int,
                     avg_edge: Optional[float], positions: int,
                     exposure: float, pnl: float):
        """Update the stats row."""
        self.stat_outcomes.set(str(outcomes))

        opp_color = GREEN if opportunities > 0 else TEXT_DIM
        self.stat_opportunities.set(str(opportunities), opp_color)

        if avg_edge is not None:
            edge_color = GREEN if avg_edge > 0 else RED if avg_edge < 0 else TEXT_DIM
            self.stat_avg_edge.set(f"{avg_edge:+.4f}", edge_color)
        else:
            self.stat_avg_edge.set("--", TEXT_DIM)

        self.stat_positions.set(str(positions))
        self.stat_exposure.set(f"{exposure:.0f}")

        pnl_color = GREEN if pnl > 0 else RED if pnl < 0 else TEXT_DIM
        self.stat_pnl.set(f"${pnl:+.2f}", pnl_color)

    def set_status(self, text: str, color: str = TEXT_DIM):
        """Update the status indicator."""
        self._status_label.config(text=text, fg=color)

    def log(self, message: str, tag: str = "info"):
        """Append a message to the arb activity log."""
        self._log_text.config(state="normal")
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self._log_text.insert("end", f"[{ts}] ", "time")
        self._log_text.insert("end", f"{message}\n", tag)
        self._log_text.see("end")
        self._log_text.config(state="disabled")

    # ──────────────────────────────────────────────────────────────
    # Convenience: bulk update from arb strategy results
    # ──────────────────────────────────────────────────────────────

    def load_scan_results(self, analyses: list, signals: list):
        """Populate the outcomes table from PriceBinaryModel analyses
        and highlight actionable signals.

        Args:
            analyses: list of PriceBinaryModel.AnalysisResult
            signals: list of ArbSignal
        """
        # Build signal lookup: coin -> signal
        sig_map = {}
        for s in signals:
            sig_map[s.coin] = s

        for a in analyses:
            for side_idx, (theo_val, mkt_val, edge_val, label) in enumerate([
                (a.theory.fair_yes, a.market_yes, a.edge_yes, "Yes"),
                (a.theory.fair_no, a.market_no, a.edge_no, "No"),
            ]):
                if mkt_val is None:
                    continue

                encoding = 10 * a.outcome_id + side_idx
                coin = f"#{encoding}"

                sig = sig_map.get(coin)
                signal_text = sig.action if sig and sig.is_actionable else ""

                iv_str = f"{a.implied_vol:.0%}" if a.implied_vol else "--"
                edge = edge_val if edge_val is not None else 0.0

                self.update_outcome(
                    coin=coin,
                    underlying=a.underlying or "--",
                    expiry=a.theory.t_years and f"{a.theory.t_years * 365:.0f}d" or "--",
                    strike=f"${a.target_price:,.0f}" if a.target_price else "--",
                    side=label,
                    theo=f"{theo_val:.4f}",
                    market=f"{mkt_val:.4f}",
                    edge=edge,
                    iv=iv_str,
                    signal=signal_text,
                )

        # Update stats
        actionable = [s for s in signals if s.is_actionable]
        avg_edge = None
        if actionable:
            avg_edge = sum(abs(s.edge) for s in actionable) / len(actionable)

        self.update_stats(
            outcomes=len(analyses),
            opportunities=len(actionable),
            avg_edge=avg_edge,
            positions=0,
            exposure=0.0,
            pnl=0.0,
        )

    def load_positions(self, positions: dict):
        """Update positions table from arb strategy's open positions.

        Args:
            positions: dict[coin, ArbPosition] from strategy.open_positions
        """
        # Remove stale rows
        current_coins = set(positions.keys())
        for coin in list(self._position_rows.keys()):
            if coin not in current_coins:
                self.remove_position(coin)

        for coin, pos in positions.items():
            self.update_position(
                coin=coin,
                side_label=pos.side_label,
                direction=pos.side,
                size=f"{pos.size:.0f}",
                entry=f"{pos.entry_price:.4f}",
                current="--",  # updated by scan
                edge=f"{pos.entry_edge:+.4f}",
                pnl=0.0,
            )

    # ──────────────────────────────────────────────────────────────
    # Internal callbacks
    # ──────────────────────────────────────────────────────────────

    def _do_scan(self):
        """Trigger a manual scan."""
        self.set_status("Scanning...", ACCENT)
        self.log("Manual scan triggered", "scan")
        if self._on_scan:
            self._on_scan()

    def _toggle_auto(self):
        """Toggle auto-scan mode."""
        enabled = self._auto_var.get()
        if self._on_toggle_auto:
            self._on_toggle_auto(enabled)
        if enabled:
            self.log("Auto-scan enabled (60s interval)", "info")
            self.set_status("Auto-scan ON", GREEN)
        else:
            self.log("Auto-scan disabled", "info")
            self.set_status("Idle", TEXT_DIM)

    def _close_selected(self):
        """Close the selected position."""
        sel = self.positions_tree.selection()
        if not sel:
            return
        # Find the coin for the selected row
        values = self.positions_tree.item(sel[0], "values")
        if values and self._on_close_position:
            coin = values[0]
            self._on_close_position(coin)

    def _toggle_auto_exec(self):
        """Toggle auto-execute mode."""
        enabled = self._auto_exec_var.get()
        if self._on_toggle_auto_exec:
            self._on_toggle_auto_exec(enabled)
        if enabled:
            self.log("⚡ Auto-execute ENABLED — trades will fire on scan", "warn")
            self._exec_status.config(text="Exec: ON", fg=YELLOW)
        else:
            self.log("Auto-execute disabled", "info")
            self._exec_status.config(text="Exec: OFF", fg=TEXT_DIM)

    # ──────────────────────────────────────────────────────────────
    # Config getters
    # ──────────────────────────────────────────────────────────────

    @property
    def min_edge(self) -> float:
        """Get the min edge value from the entry field."""
        try:
            return float(self._min_edge_var.get())
        except ValueError:
            return 0.03

    @property
    def vol_override(self) -> Optional[float]:
        """Get the vol override, or None if 'auto'."""
        v = self._vol_var.get().strip().lower()
        if v in ("auto", ""):
            return None
        try:
            return float(v)
        except ValueError:
            return None

    @property
    def auto_execute(self) -> bool:
        """Whether auto-execute is enabled."""
        return self._auto_exec_var.get()

    @property
    def min_strength(self) -> float:
        """Minimum signal strength to auto-execute (0.0 – 1.0)."""
        try:
            return max(0.0, min(1.0, float(self._min_strength_var.get())))
        except ValueError:
            return 0.30

    @property
    def kelly_fraction(self) -> float:
        """Kelly fraction for position sizing (0.0 – 1.0)."""
        try:
            return max(0.01, min(1.0, float(self._kelly_var.get())))
        except ValueError:
            return 0.25

    @property
    def max_positions(self) -> int:
        """Maximum concurrent arb positions."""
        try:
            return max(1, int(self._max_pos_var.get()))
        except ValueError:
            return 5

    @property
    def max_exposure(self) -> float:
        """Maximum total exposure in USDC."""
        try:
            return max(1.0, float(self._max_exposure_var.get()))
        except ValueError:
            return 100.0

    @property
    def use_ioc(self) -> bool:
        """Whether to use IOC (market-like) orders."""
        return self._ioc_var.get()
