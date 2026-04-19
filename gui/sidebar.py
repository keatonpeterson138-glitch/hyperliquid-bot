"""Left sidebar – account info, quick stats, active position card."""
from __future__ import annotations
import tkinter as tk
from gui.theme import *
from gui.components import Card, StatBox, StatusDot, ActionButton


class Sidebar(tk.Frame):
    """Left-hand sidebar containing account, stats, position panels."""

    def __init__(self, parent, **kw):
        super().__init__(parent, bg=BG_DARK, width=280, **kw)
        self.pack_propagate(False)

        # ── Top accent stripe ───────────────────────────────────
        stripe = tk.Frame(self, bg=ACCENT, height=3)
        stripe.pack(fill="x")

        # ── Logo / title ────────────────────────────────────────
        header = tk.Frame(self, bg=BG_DARK)
        header.pack(fill="x", padx=PAD_X, pady=(14, 4))
        tk.Label(header, text="HYPERLIQUID", font=(FONT_FAMILY, 16, "bold"),
                 bg=BG_DARK, fg=ACCENT).pack(side="left")
        tk.Label(header, text="  Bot", font=(FONT_FAMILY, 16),
                 bg=BG_DARK, fg=TEXT_DIM).pack(side="left")

        # ── Connection status ───────────────────────────────────
        self.status_dot = StatusDot(self, "Disconnected", RED)
        self.status_dot.pack(fill="x", padx=PAD_X, pady=(10, 2))
        self.bot_status = StatusDot(self, "Bot Stopped", RED)
        self.bot_status.pack(fill="x", padx=PAD_X, pady=(0, 10))

        # ── Account card ────────────────────────────────────────
        acct = Card(self, title="Account")
        acct.pack(fill="x", padx=PAD_X, pady=PAD_Y)

        self.network_stat = StatBox(acct, "Network", "Testnet")
        self.network_stat.pack(fill="x", padx=CARD_PAD, pady=(4, 2))
        self.address_stat = StatBox(acct, "Wallet", "0x…")
        self.address_stat.pack(fill="x", padx=CARD_PAD, pady=2)
        self.balance_stat = StatBox(acct, "Account Balance", "$0.00", GREEN)
        self.balance_stat.pack(fill="x", padx=CARD_PAD, pady=(2, CARD_PAD))

        # ── Quick Stats card ────────────────────────────────────
        stats = Card(self, title="Session Stats")
        stats.pack(fill="x", padx=PAD_X, pady=PAD_Y)

        row1 = tk.Frame(stats, bg=BG_CARD)
        row1.pack(fill="x", padx=CARD_PAD, pady=(4, 2))
        self.daily_pnl = StatBox(row1, "Daily P&L", "$0.00")
        self.daily_pnl.pack(side="left", expand=True, fill="x")
        self.total_trades = StatBox(row1, "Trades", "0")
        self.total_trades.pack(side="left", expand=True, fill="x")

        row2 = tk.Frame(stats, bg=BG_CARD)
        row2.pack(fill="x", padx=CARD_PAD, pady=(2, CARD_PAD))
        self.win_rate = StatBox(row2, "Win Rate", "-- %")
        self.win_rate.pack(side="left", expand=True, fill="x")
        self.signal_str = StatBox(row2, "Last Signal", "--")
        self.signal_str.pack(side="left", expand=True, fill="x")

        # ── Active Positions card (scrollable, multi-position) ────
        self._pos_card = Card(self, title="Active Positions")
        self._pos_card.pack(fill="x", padx=PAD_X, pady=PAD_Y)

        # Container inside the card for position rows
        self._pos_container = tk.Frame(self._pos_card, bg=BG_CARD)
        self._pos_container.pack(fill="x", padx=CARD_PAD, pady=(4, CARD_PAD))

        # "No positions" placeholder
        self._no_pos_label = tk.Label(
            self._pos_container, text="No open positions",
            font=FONT_SMALL, bg=BG_CARD, fg=TEXT_DIM)
        self._no_pos_label.pack(anchor="w", pady=4)

        # Track position row widgets
        self._pos_rows: list[tk.Frame] = []

    # ── Public update helpers ───────────────────────────────────
    def update_connection(self, connected: bool, network: str):
        if connected:
            self.status_dot.set("Connected", GREEN)
            self.network_stat.set(network, GREEN if network == "Mainnet" else YELLOW)
        else:
            self.status_dot.set("Disconnected", RED)

    def update_bot_status(self, running: bool):
        if running:
            self.bot_status.set("Bot Running", GREEN)
        else:
            self.bot_status.set("Bot Stopped", RED)

    def update_account(self, address: str, balance: float):
        short_addr = f"{address[:6]}\u2026{address[-4:]}" if len(address) > 10 else address
        self.address_stat.set(short_addr)
        color = GREEN if balance > 0 else RED
        self.balance_stat.set(f"${balance:,.2f}", color)

    def set_transfer_callback(self, callback):
        """Set the callback for the Transfer button (kept for compatibility)."""
        pass

    def update_position(self, position: dict | None):
        """Legacy single-position update — wraps into list form."""
        if position:
            self.update_positions([position])
        else:
            self.update_positions([])

    def update_positions(self, positions: list[dict]):
        """Display all open positions in the sidebar card.

        Each position dict: {symbol, type, entry_price, size, unrealized_pnl}
        """
        # Clear old rows
        for row in self._pos_rows:
            row.destroy()
        self._pos_rows.clear()

        if not positions:
            self._no_pos_label.pack(anchor="w", pady=4)
            return

        self._no_pos_label.pack_forget()

        for p in positions:
            sym = p.get("symbol", "?")
            side = p.get("type", "NONE")
            entry = p.get("entry_price", 0)
            size = p.get("size", 0)
            pnl = p.get("unrealized_pnl", 0)

            side_color = GREEN if side == "LONG" else RED
            pnl_color = GREEN if pnl >= 0 else RED

            # Container for this position
            row = tk.Frame(self._pos_container, bg=BG_CARD)
            row.pack(fill="x", pady=(2, 4))
            self._pos_rows.append(row)

            # Row 1: symbol + side
            r1 = tk.Frame(row, bg=BG_CARD)
            r1.pack(fill="x")
            tk.Label(r1, text=sym, font=(FONT_FAMILY, 11, "bold"),
                     bg=BG_CARD, fg=TEXT).pack(side="left")
            tk.Label(r1, text=f"  {side}", font=FONT_SMALL,
                     bg=BG_CARD, fg=side_color).pack(side="left")
            tk.Label(r1, text=f"${pnl:+,.2f}", font=FONT_MONO_SM,
                     bg=BG_CARD, fg=pnl_color).pack(side="right")

            # Row 2: entry / size
            r2 = tk.Frame(row, bg=BG_CARD)
            r2.pack(fill="x")
            tk.Label(r2, text=f"Entry ${entry:,.2f}", font=FONT_TINY,
                     bg=BG_CARD, fg=TEXT_DIM).pack(side="left")
            tk.Label(r2, text=f"Size {size:.4f}", font=FONT_TINY,
                     bg=BG_CARD, fg=TEXT_DIM).pack(side="right")

            # Separator line (except after last)
            if p is not positions[-1]:
                tk.Frame(row, bg=BORDER, height=1).pack(fill="x", pady=(4, 0))

    def update_stats(self, daily_pnl: float, trades: int,
                     wins: int, last_signal: str):
        pnl_color = GREEN if daily_pnl >= 0 else RED
        self.daily_pnl.set(f"${daily_pnl:,.2f}", pnl_color)
        self.total_trades.set(str(trades))
        wr = (wins / trades * 100) if trades > 0 else 0
        self.win_rate.set(f"{wr:.0f}%", GREEN if wr >= 50 else YELLOW)
        sig_color = GREEN if "LONG" in last_signal else (RED if "SHORT" in last_signal else TEXT_DIM)
        self.signal_str.set(last_signal, sig_color)
