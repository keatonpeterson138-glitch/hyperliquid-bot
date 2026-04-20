"""/wallet — balance, open positions, P&L, recent activity for the sidebar Wallet tab."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.services.wallet import WalletService

router = APIRouter(tags=["wallet"])


def get_wallet_service() -> WalletService:
    raise HTTPException(status_code=503, detail="WalletService not configured")


WalletDep = Annotated[WalletService, Depends(get_wallet_service)]


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
