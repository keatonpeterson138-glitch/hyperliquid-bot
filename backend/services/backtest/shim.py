"""ExchangeShim — simulated fills for backtesting.

Matches just enough of the live ``HyperliquidClient`` surface that a
``BacktestRunner`` can drive it the same way ``SlotRunner`` drives the
real client. All fills honor slippage + fees deterministically so runs
are reproducible byte-for-byte.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class SimulatedPosition:
    symbol: str
    is_long: bool
    size_usd: float
    entry_price: float
    entered_at: datetime


@dataclass
class SimulatedFill:
    timestamp: datetime
    symbol: str
    side: str                   # 'buy' | 'sell'
    size_usd: float
    price: float
    fee_usd: float
    realised_pnl_usd: float = 0.0
    reason: str = ""


@dataclass
class ExchangeShim:
    slippage_bps: float = 1.0       # 0.01% per fill
    fee_bps: float = 2.0            # 0.02% per fill — taker fee
    funding_bps_per_bar: float = 0.0  # 0 = off; e.g. 0.01 for 1h bars ≈ 8 hourly → daily ≈ 0.08%
    _position: SimulatedPosition | None = None
    _current_price: float = 0.0
    _current_ts: datetime | None = None
    fills: list[SimulatedFill] = field(default_factory=list)
    cash_usd: float = 0.0
    accumulated_funding: float = 0.0

    # ── Clock (called by the runner before each decision) ─────────────

    def set_clock(self, ts: datetime, price: float) -> None:
        # Apply funding on the previous position before stepping.
        if self._position is not None and self.funding_bps_per_bar != 0.0:
            notional = self._position.size_usd
            funding = notional * self.funding_bps_per_bar / 10_000.0
            sign = -1.0 if self._position.is_long else 1.0  # longs pay positive funding
            self.accumulated_funding += sign * funding
            self.cash_usd += sign * funding
        self._current_ts = ts
        self._current_price = price

    # ── Exchange surface (subset of HyperliquidClient) ─────────────────

    def get_market_price(self, symbol: str) -> float | None:  # noqa: ARG002
        return self._current_price if self._current_price > 0 else None

    def place_market_order(
        self,
        symbol: str,
        is_buy: bool,
        size_usd: float,
        leverage: int,  # noqa: ARG002 — simulated margin only tracks notional
    ) -> dict[str, Any]:
        if self._current_ts is None:
            raise RuntimeError("set_clock() not called before order")
        fill_price = self._apply_slippage(self._current_price, is_buy)
        fee = size_usd * self.fee_bps / 10_000.0
        self.cash_usd -= fee

        realised = 0.0
        if self._position is not None:
            if is_buy == self._position.is_long:
                # Scaling up — track weighted average.
                new_size = self._position.size_usd + size_usd
                avg_entry = (
                    self._position.entry_price * self._position.size_usd
                    + fill_price * size_usd
                ) / new_size
                self._position = SimulatedPosition(
                    symbol=symbol,
                    is_long=self._position.is_long,
                    size_usd=new_size,
                    entry_price=avg_entry,
                    entered_at=self._position.entered_at,
                )
            else:
                # Opposite direction: close (possibly flip).
                realised = self._realise(fill_price)
                close_size = self._position.size_usd
                remaining = size_usd - close_size
                self._position = None
                if remaining > 1e-9:
                    # Flipped — open the remainder.
                    self._position = SimulatedPosition(
                        symbol=symbol,
                        is_long=is_buy,
                        size_usd=remaining,
                        entry_price=fill_price,
                        entered_at=self._current_ts,
                    )
        else:
            self._position = SimulatedPosition(
                symbol=symbol,
                is_long=is_buy,
                size_usd=size_usd,
                entry_price=fill_price,
                entered_at=self._current_ts,
            )

        self.fills.append(SimulatedFill(
            timestamp=self._current_ts,
            symbol=symbol,
            side="buy" if is_buy else "sell",
            size_usd=size_usd,
            price=fill_price,
            fee_usd=fee,
            realised_pnl_usd=realised,
            reason="market",
        ))

        return {
            "order_id": f"sim_{len(self.fills)}",
            "exchange_order_id": f"sim_{len(self.fills)}",
            "fill_price": fill_price,
        }

    def close_position(self, symbol: str, dex: str = "") -> dict[str, Any]:  # noqa: ARG002
        if self._position is None:
            return {"order_id": None, "fill_price": None, "skipped": True}
        is_buy = not self._position.is_long  # sell a long, buy a short back
        size = self._position.size_usd
        return self.place_market_order(symbol, is_buy=is_buy, size_usd=size, leverage=1)

    # ── Read helpers ──────────────────────────────────────────────────

    @property
    def position(self) -> SimulatedPosition | None:
        return self._position

    def equity(self) -> float:
        """Cash + MTM of open position."""
        mtm = 0.0
        if self._position is not None and self._current_price > 0:
            direction = 1.0 if self._position.is_long else -1.0
            pnl_pct = (self._current_price - self._position.entry_price) / self._position.entry_price
            mtm = self._position.size_usd * pnl_pct * direction
        return self.cash_usd + mtm

    # ── Internals ─────────────────────────────────────────────────────

    def _apply_slippage(self, px: float, is_buy: bool) -> float:
        bps = self.slippage_bps / 10_000.0
        return px * (1.0 + bps) if is_buy else px * (1.0 - bps)

    def _realise(self, exit_price: float) -> float:
        assert self._position is not None
        direction = 1.0 if self._position.is_long else -1.0
        pct = (exit_price - self._position.entry_price) / self._position.entry_price
        pnl = self._position.size_usd * pct * direction
        self.cash_usd += pnl
        return pnl
