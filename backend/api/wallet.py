"""/wallet — balance, open positions, P&L, recent activity for the sidebar Wallet tab.

Live positions / fills / realised-PnL-series come directly from
Hyperliquid's public Info endpoint (``clearinghouseState`` + ``userFills``
— no private key required, just the master wallet address). The caller
passes ``wallet_address`` either as a query param or the app falls back
to the one stored in the settings JSON.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.services.hl_user_state import HyperliquidUserState
from backend.services.settings_store import SettingsStore
from backend.services.wallet import WalletService

router = APIRouter(tags=["wallet"])


def get_wallet_service() -> WalletService:
    raise HTTPException(status_code=503, detail="WalletService not configured")


def get_settings_for_wallet() -> SettingsStore:
    raise HTTPException(status_code=503, detail="SettingsStore not configured")


WalletDep = Annotated[WalletService, Depends(get_wallet_service)]
SettingsDep = Annotated[SettingsStore, Depends(get_settings_for_wallet)]


def _resolve_address(wallet_address: str | None, settings: SettingsStore) -> str:
    """Pick the wallet address — query param wins, otherwise settings.extras.wallet_address."""
    if wallet_address:
        return wallet_address
    extras = settings.all().extras or {}
    stored = extras.get("wallet_address") if isinstance(extras, dict) else None
    if stored:
        return str(stored)
    raise HTTPException(
        status_code=400,
        detail="no wallet_address — pass ?wallet_address=0x... or set it in Settings",
    )


class WalletPositionOut(BaseModel):
    symbol: str
    side: str
    size_usd: float
    entry_price: float | None = None
    unrealised_pnl_usd: float | None = None


class WalletSummaryOut(BaseModel):
    wallet_address: str | None = None
    usdc_balance: float | None = None
    total_notional_usd: float
    unrealised_pnl_usd: float
    realised_pnl_session_usd: float
    realised_pnl_all_time_usd: float
    fees_paid_all_time_usd: float
    positions: list[WalletPositionOut] = Field(default_factory=list)
    open_orders: int = 0
    last_updated: datetime


class RecentOrderOut(BaseModel):
    id: str
    symbol: str
    side: str
    size_usd: float
    status: str
    entry_price: float | None
    fill_price: float | None
    created_at: datetime | None


@router.get("/wallet/summary", response_model=WalletSummaryOut)
def get_wallet_summary(svc: WalletDep, wallet_address: str | None = None) -> WalletSummaryOut:
    s = svc.summary(wallet_address=wallet_address)
    return WalletSummaryOut(
        wallet_address=s.wallet_address,
        usdc_balance=s.usdc_balance,
        total_notional_usd=s.total_notional_usd,
        unrealised_pnl_usd=s.unrealised_pnl_usd,
        realised_pnl_session_usd=s.realised_pnl_session_usd,
        realised_pnl_all_time_usd=s.realised_pnl_all_time_usd,
        fees_paid_all_time_usd=s.fees_paid_all_time_usd,
        positions=[
            WalletPositionOut(
                symbol=p.symbol, side=p.side, size_usd=p.size_usd,
                entry_price=p.entry_price, unrealised_pnl_usd=p.unrealised_pnl_usd,
            )
            for p in s.positions
        ],
        open_orders=s.open_orders,
        last_updated=s.last_updated,
    )


@router.get("/wallet/activity", response_model=list[RecentOrderOut])
def get_recent_activity(svc: WalletDep, limit: int = 25) -> list[RecentOrderOut]:
    orders = svc.recent_activity(limit)
    return [
        RecentOrderOut(
            id=o.id, symbol=o.symbol, side=o.side, size_usd=o.size_usd,
            status=o.status, entry_price=o.entry_price, fill_price=o.fill_price,
            created_at=o.created_at,
        )
        for o in orders
    ]


# ── Live Hyperliquid user state (positions / fills / PnL) ─────────
# These endpoints hit Hyperliquid's public Info API — read-only, no
# private key needed. Pass ``wallet_address`` or set it in Settings.

class LivePositionOut(BaseModel):
    symbol: str
    side: str
    size: float
    size_usd: float
    entry_price: float | None = None
    mark_price: float | None = None
    unrealised_pnl_usd: float
    leverage: float | None = None
    liquidation_price: float | None = None
    margin_used_usd: float | None = None


class LivePositionsResponse(BaseModel):
    wallet_address: str
    account_value_usd: float
    total_margin_used_usd: float
    total_notional_usd: float
    unrealised_pnl_usd: float
    withdrawable_usd: float
    positions: list[LivePositionOut] = Field(default_factory=list)


class FillOut(BaseModel):
    symbol: str
    side: str
    px: float
    sz: float
    closed_pnl_usd: float | None = None
    fee_usd: float
    timestamp: datetime
    is_close: bool
    oid: int


class PnLPoint(BaseModel):
    timestamp: datetime
    delta: float
    cumulative: float


class PnLSeriesResponse(BaseModel):
    wallet_address: str
    window: Literal["1d", "1w", "1m", "3m"]
    bucket: Literal["hour", "day"]
    points: list[PnLPoint] = Field(default_factory=list)
    realised_total_usd: float = 0.0
    fee_total_usd: float = 0.0


def _user_state(testnet: bool = False) -> HyperliquidUserState:
    return HyperliquidUserState(testnet=testnet)


@router.get("/wallet/positions", response_model=LivePositionsResponse)
def live_positions(
    settings: SettingsDep,
    wallet_address: str | None = None,
) -> LivePositionsResponse:
    addr = _resolve_address(wallet_address, settings)
    hl = _user_state(testnet=settings.all().testnet)
    try:
        summary = hl.clearinghouse_state(addr)
    finally:
        hl.close()
    return LivePositionsResponse(
        wallet_address=summary.wallet_address,
        account_value_usd=summary.account_value_usd,
        total_margin_used_usd=summary.total_margin_used_usd,
        total_notional_usd=summary.total_notional_usd,
        unrealised_pnl_usd=summary.unrealised_pnl_usd,
        withdrawable_usd=summary.withdrawable_usd,
        positions=[
            LivePositionOut(
                symbol=p.symbol, side=p.side, size=p.size, size_usd=p.size_usd,
                entry_price=p.entry_price, mark_price=p.mark_price,
                unrealised_pnl_usd=p.unrealised_pnl_usd,
                leverage=p.leverage, liquidation_price=p.liquidation_price,
                margin_used_usd=p.margin_used_usd,
            )
            for p in summary.positions
        ],
    )


@router.get("/wallet/fills", response_model=list[FillOut])
def live_fills(
    settings: SettingsDep,
    wallet_address: str | None = None,
    limit: int = 200,
) -> list[FillOut]:
    addr = _resolve_address(wallet_address, settings)
    hl = _user_state(testnet=settings.all().testnet)
    try:
        fills = hl.user_fills(addr, limit=max(1, min(limit, 2000)))
    finally:
        hl.close()
    return [
        FillOut(
            symbol=f.symbol, side=f.side, px=f.px, sz=f.sz,
            closed_pnl_usd=f.closed_pnl_usd, fee_usd=f.fee_usd,
            timestamp=f.timestamp, is_close=f.is_close, oid=f.oid,
        )
        for f in fills
    ]


_WINDOW_DAYS = {"1d": 1, "1w": 7, "1m": 30, "3m": 90}


@router.get("/wallet/pnl", response_model=PnLSeriesResponse)
def live_pnl(
    settings: SettingsDep,
    wallet_address: str | None = None,
    window: Literal["1d", "1w", "1m", "3m"] = "1m",
) -> PnLSeriesResponse:
    addr = _resolve_address(wallet_address, settings)
    days = _WINDOW_DAYS[window]
    bucket = "hour" if window == "1d" else "day"
    hl = _user_state(testnet=settings.all().testnet)
    try:
        points_raw = hl.pnl_series(addr, days=days, bucket=bucket)
    finally:
        hl.close()
    points = [
        PnLPoint(
            timestamp=datetime.fromisoformat(p["timestamp"]),
            delta=float(p["delta"]),
            cumulative=float(p["cumulative"]),
        )
        for p in points_raw
    ]
    realised_total = points[-1].cumulative if points else 0.0
    # Approximate fees from fills again — cheap since we cached response size.
    hl2 = _user_state(testnet=settings.all().testnet)
    try:
        recent = hl2.user_fills(addr, limit=2000)
    finally:
        hl2.close()
    from datetime import timedelta as _td
    cutoff_dt = datetime.fromisoformat(points[0].timestamp.isoformat()) if points else datetime.now().astimezone() - _td(days=days)
    fee_total = sum(f.fee_usd for f in recent if f.timestamp >= cutoff_dt)
    return PnLSeriesResponse(
        wallet_address=addr,
        window=window,
        bucket=bucket,
        points=points,
        realised_total_usd=realised_total,
        fee_total_usd=fee_total,
    )


class WalletAddressUpdate(BaseModel):
    wallet_address: str


@router.put("/wallet/address")
def set_wallet_address(req: WalletAddressUpdate, settings: SettingsDep) -> dict[str, Any]:
    """Persist the master wallet address to settings so other endpoints
    can pick it up without the caller passing it every time."""
    addr = req.wallet_address.strip()
    if not addr:
        raise HTTPException(status_code=400, detail="wallet_address required")
    settings.update({"extras": {"wallet_address": addr}})
    return {"wallet_address": addr}
