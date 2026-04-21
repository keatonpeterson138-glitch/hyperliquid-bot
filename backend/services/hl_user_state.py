"""HyperliquidUserState — read-only queries of a wallet's perp state via
the public Info endpoint.

Doesn't need a private key — just the master wallet address. Backs the
Active Positions / Trade History / PnL Chart UI.

Endpoints used:
  * ``POST /info {"type": "clearinghouseState", "user": "<address>"}``
      Returns margin summary + per-asset positions + perp metadata.
  * ``POST /info {"type": "userFills", "user": "<address>"}``
      Returns the last ~2000 fills (most-recent first).
  * ``POST /info {"type": "userFundingHistory", "user": "<address>", ...}``
      Funding payments over a window.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

logger = logging.getLogger(__name__)

MAINNET_INFO = "https://api.hyperliquid.xyz/info"
TESTNET_INFO = "https://api.hyperliquid-testnet.xyz/info"


@dataclass
class Position:
    symbol: str
    side: str                       # "long" | "short"
    size: float                     # in coin units (+ for long, - for short in raw HL)
    size_usd: float                 # |size| × mark
    entry_price: float | None
    mark_price: float | None
    unrealised_pnl_usd: float
    leverage: float | None
    liquidation_price: float | None
    margin_used_usd: float | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Fill:
    symbol: str
    side: str                       # "long" | "short" (the direction of the fill)
    px: float
    sz: float                       # in coin units
    closed_pnl_usd: float | None    # realised PnL on closes (None on opens)
    fee_usd: float
    timestamp: datetime
    is_close: bool                  # True when this fill closes a position
    oid: int
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class UserSummary:
    wallet_address: str
    account_value_usd: float
    total_margin_used_usd: float
    total_notional_usd: float
    unrealised_pnl_usd: float
    withdrawable_usd: float
    positions: list[Position] = field(default_factory=list)


class HyperliquidUserState:
    def __init__(self, *, testnet: bool = False, timeout: float = 10.0,
                 http_client: httpx.Client | None = None) -> None:
        self.endpoint = TESTNET_INFO if testnet else MAINNET_INFO
        self._client = http_client or httpx.Client(timeout=timeout)
        self._owns_client = http_client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    # ── reads ─────────────────────────────────────────────────────

    def _post(self, body: dict[str, Any]) -> Any:
        resp = self._client.post(self.endpoint, json=body)
        resp.raise_for_status()
        return resp.json()

    def clearinghouse_state(self, wallet_address: str) -> UserSummary:
        data = self._post({"type": "clearinghouseState", "user": wallet_address})
        margin = (data.get("marginSummary") or {})
        cross = (data.get("crossMarginSummary") or {})
        summary = UserSummary(
            wallet_address=wallet_address,
            account_value_usd=float(margin.get("accountValue") or 0.0),
            total_margin_used_usd=float(margin.get("totalMarginUsed") or 0.0),
            total_notional_usd=float(margin.get("totalNtlPos") or 0.0),
            unrealised_pnl_usd=0.0,
            withdrawable_usd=float(data.get("withdrawable") or 0.0),
        )
        # Positions sit under assetPositions[*].position
        positions: list[Position] = []
        unreal_total = 0.0
        for a in data.get("assetPositions") or []:
            p = a.get("position") or {}
            coin = p.get("coin") or ""
            szi = float(p.get("szi") or 0.0)
            if szi == 0:
                continue
            entry = _to_float(p.get("entryPx"))
            liq = _to_float((p.get("liquidationPx")))
            pnl = float(p.get("unrealizedPnl") or 0.0)
            unreal_total += pnl
            margin_used = _to_float(p.get("marginUsed"))
            lev_obj = p.get("leverage") or {}
            lev_val = _to_float(lev_obj.get("value"))
            mark = entry  # good-enough approximation pre-ticker join
            positions.append(Position(
                symbol=coin,
                side="long" if szi > 0 else "short",
                size=szi,
                size_usd=abs(szi) * (mark or 0.0),
                entry_price=entry,
                mark_price=mark,
                unrealised_pnl_usd=pnl,
                leverage=lev_val,
                liquidation_price=liq,
                margin_used_usd=margin_used,
                raw=p,
            ))
        summary.positions = positions
        summary.unrealised_pnl_usd = unreal_total
        # Cross margin summary provides the total_notional once trades are active.
        if cross and cross.get("totalNtlPos"):
            summary.total_notional_usd = float(cross.get("totalNtlPos") or summary.total_notional_usd)
        return summary

    def user_fills(self, wallet_address: str, *, limit: int = 200) -> list[Fill]:
        data = self._post({"type": "userFills", "user": wallet_address})
        fills: list[Fill] = []
        for row in (data or [])[:limit]:
            dir_ = str(row.get("dir") or "")      # e.g. "Open Long", "Close Short", "Buy", "Sell"
            side = "long" if "Long" in dir_ or dir_.lower() == "buy" else "short"
            is_close = dir_.startswith("Close") or "Close" in dir_
            try:
                ts = datetime.fromtimestamp(int(row.get("time", 0)) / 1000, tz=UTC)
            except (TypeError, ValueError):
                ts = datetime.now(UTC)
            closed_pnl = _to_float(row.get("closedPnl"))
            fills.append(Fill(
                symbol=str(row.get("coin") or ""),
                side=side,
                px=float(row.get("px") or 0.0),
                sz=float(row.get("sz") or 0.0),
                closed_pnl_usd=closed_pnl if is_close else None,
                fee_usd=float(row.get("fee") or 0.0),
                timestamp=ts,
                is_close=is_close,
                oid=int(row.get("oid") or 0),
                raw=row,
            ))
        return fills

    def pnl_series(
        self,
        wallet_address: str,
        *,
        days: int = 30,
        bucket: str = "day",          # 'hour' | 'day'
    ) -> list[dict[str, Any]]:
        """Realised PnL per bucket — synthesized from userFills closedPnl.

        Unrealized PnL is point-in-time and isn't included; use
        ``clearinghouse_state().unrealised_pnl_usd`` for that.
        """
        fills = self.user_fills(wallet_address, limit=2000)
        cutoff = datetime.now(UTC) - timedelta(days=days)
        buckets: dict[datetime, float] = {}
        for f in fills:
            if f.timestamp < cutoff:
                continue
            if not f.is_close or f.closed_pnl_usd is None:
                continue
            key = f.timestamp.replace(minute=0, second=0, microsecond=0)
            if bucket == "day":
                key = key.replace(hour=0)
            buckets[key] = buckets.get(key, 0.0) + f.closed_pnl_usd - f.fee_usd
        # Emit cumulative series from oldest → newest.
        ordered = sorted(buckets.items())
        cum = 0.0
        out: list[dict[str, Any]] = []
        for ts, delta in ordered:
            cum += delta
            out.append({"timestamp": ts.isoformat(), "delta": delta, "cumulative": cum})
        return out


def _to_float(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
