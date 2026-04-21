"""/balances — per-broker end-of-day equity snapshots.

Manual entries via POST; auto-refresh via POST /balances/refresh which
tries each broker that has an official API (Hyperliquid, Coinbase, Kraken).
Brokers without retail APIs (Robinhood, Fidelity) stay manual.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.services.balances_store import SUPPORTED_BROKERS, BalancesStore
from backend.services.credentials_store import CredentialsStore
from backend.services.live_market import LiveMarketService
from backend.services.plaid_service import PlaidService
from backend.services.plaid_store import PlaidStore

router = APIRouter(tags=["balances"])


def get_balances_store() -> BalancesStore:
    raise HTTPException(status_code=503, detail="BalancesStore not configured")


def get_credentials_for_balances() -> CredentialsStore:
    raise HTTPException(status_code=503, detail="CredentialsStore not configured")


def get_live_market_for_balances() -> LiveMarketService:
    raise HTTPException(status_code=503, detail="LiveMarketService not configured")


def get_plaid_service_for_balances() -> PlaidService | None:
    # Plaid-less deployments are a legitimate state — we return None and
    # the refresh skips Plaid instead of 503-ing the whole endpoint.
    return None


def get_plaid_store_for_balances() -> PlaidStore | None:
    return None


StoreDep = Annotated[BalancesStore, Depends(get_balances_store)]
CredsDep = Annotated[CredentialsStore, Depends(get_credentials_for_balances)]
LiveDep = Annotated[LiveMarketService, Depends(get_live_market_for_balances)]
PlaidSvcDep = Annotated["PlaidService | None", Depends(get_plaid_service_for_balances)]
PlaidStoreDep = Annotated["PlaidStore | None", Depends(get_plaid_store_for_balances)]


class BalanceSnapshotOut(BaseModel):
    id: int | None
    broker: str
    asof: datetime
    equity_usd: float
    cash_usd: float | None = None
    buying_power: float | None = None
    unrealised_pnl: float | None = None
    realised_pnl_today: float | None = None
    source_note: str = "manual"
    created_at: datetime | None = None


class BalanceSummaryResponse(BaseModel):
    total_equity_usd: float
    per_broker: list[BalanceSnapshotOut] = Field(default_factory=list)


class BalanceCreate(BaseModel):
    broker: str
    equity_usd: float
    cash_usd: float | None = None
    buying_power: float | None = None
    unrealised_pnl: float | None = None
    realised_pnl_today: float | None = None
    asof: datetime | None = None
    source_note: str = "manual"


class RefreshResponse(BaseModel):
    updated: list[BalanceSnapshotOut] = Field(default_factory=list)
    skipped: list[dict[str, str]] = Field(default_factory=list)


SUPPORTED_LIST = list(SUPPORTED_BROKERS)


@router.get("/balances/supported", response_model=list[str])
def supported() -> list[str]:
    return SUPPORTED_LIST


@router.get("/balances", response_model=BalanceSummaryResponse)
def latest(store: StoreDep) -> BalanceSummaryResponse:
    snaps = store.latest_per_broker()
    total = sum(s.equity_usd for s in snaps if s.equity_usd is not None)
    return BalanceSummaryResponse(
        total_equity_usd=float(total),
        per_broker=[_to_out(s) for s in snaps],
    )


@router.post("/balances", response_model=BalanceSnapshotOut)
def create(req: BalanceCreate, store: StoreDep) -> BalanceSnapshotOut:
    try:
        s = store.record(
            broker=req.broker, equity_usd=req.equity_usd,
            cash_usd=req.cash_usd, buying_power=req.buying_power,
            unrealised_pnl=req.unrealised_pnl,
            realised_pnl_today=req.realised_pnl_today,
            asof=req.asof, source_note=req.source_note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_out(s)


@router.delete("/balances/{bid}", status_code=204)
def delete(bid: int, store: StoreDep) -> None:
    store.delete(bid)


@router.get("/balances/history/{broker}", response_model=list[BalanceSnapshotOut])
def history(broker: str, store: StoreDep, limit: int = 100) -> list[BalanceSnapshotOut]:
    return [_to_out(s) for s in store.history(broker, limit=limit)]


@router.post("/balances/refresh", response_model=RefreshResponse)
def refresh(
    store: StoreDep,
    creds: CredsDep,
    live: LiveDep,
    plaid_svc: PlaidSvcDep,
    plaid_store: PlaidStoreDep,
) -> RefreshResponse:
    """Best-effort pull for every connected source:

    * Plaid — sums tracked accounts per broker_label → one row per broker
      (handles Fidelity + Robinhood + etc. when linked via Plaid).
    * E*Trade — direct OAuth API (wired via /etrade/refresh).
    * Coinbase / Kraken / Hyperliquid — direct APIs, added incrementally.
    """
    updated: list[BalanceSnapshotOut] = []
    skipped: list[dict[str, str]] = []

    # ── Plaid — aggregate tracked accounts by broker_label ───────
    if plaid_svc is not None and plaid_store is not None:
        try:
            tracked = plaid_store.list_tracked_accounts()
        except Exception as exc:  # noqa: BLE001
            tracked = []
            skipped.append({"broker": "plaid", "reason": f"list_tracked_accounts failed: {exc}"})

        if not tracked:
            skipped.append({"broker": "plaid", "reason": "no tracked accounts — link via the Balances page then toggle which to track"})
        else:
            # Group accounts by item_id (one Plaid call per item) so one
            # HTTP round-trip hydrates every account on that institution.
            items_map: dict[str, list] = {}
            for a in tracked:
                items_map.setdefault(a.item_id, []).append(a)

            # Per-broker running totals — each broker_label gets a summed row.
            per_broker: dict[str, dict[str, float]] = {}
            raw_per_broker: dict[str, list[dict[str, Any]]] = {}

            for item_id, accounts in items_map.items():
                item = plaid_store.get_item(item_id)
                if item is None:
                    continue
                try:
                    resp = plaid_svc.accounts_balance_get(item.access_token)
                except RuntimeError as exc:
                    skipped.append({"broker": item.institution_name or "plaid", "reason": f"balance fetch failed: {exc}"})
                    continue

                by_plaid_id = {a["account_id"]: a for a in resp.get("accounts", [])}
                for acct in accounts:
                    data = by_plaid_id.get(acct.plaid_account_id)
                    if not data:
                        continue
                    bal = data.get("balances", {}) or {}
                    equity = bal.get("current")
                    available = bal.get("available")
                    if equity is None:
                        continue
                    broker = acct.broker_label or "other"
                    totals = per_broker.setdefault(broker, {"equity": 0.0, "cash": 0.0})
                    totals["equity"] += float(equity)
                    if available is not None:
                        totals["cash"] += float(available)
                    raw_per_broker.setdefault(broker, []).append({
                        "account_id": acct.plaid_account_id,
                        "name": acct.name,
                        "mask": acct.mask,
                        "balance": bal,
                    })

            for broker, totals in per_broker.items():
                try:
                    snap = store.record(
                        broker=broker,
                        equity_usd=totals["equity"],
                        cash_usd=totals["cash"] or None,
                        source_note="plaid",
                        raw={"plaid_accounts": raw_per_broker.get(broker, [])},
                    )
                    updated.append(_to_out(snap))
                except ValueError as exc:
                    skipped.append({"broker": broker, "reason": str(exc)})
    else:
        skipped.append({"broker": "plaid", "reason": "Plaid not configured — add a 'plaid' API key and link an institution"})

    # ── Direct APIs — incremental; stub until each one is wired in ──
    # Coinbase — official API. Keep on "next iteration" until the
    # CB-ACCESS-SIGN HMAC signer lands.
    cb = creds.first_for("coinbase")
    if cb and cb.api_key and cb.api_secret:
        skipped.append({"broker": "coinbase", "reason": "key present — Coinbase Advanced Trade HMAC refresh lands next iteration"})
    else:
        skipped.append({"broker": "coinbase", "reason": "no api_key/api_secret under provider 'coinbase'"})

    skipped.append({"broker": "hyperliquid", "reason": "needs vault unlock + live HyperliquidClient (Phase 11 wiring)"})
    skipped.append({"broker": "kraken", "reason": "REST refresh pending — stored under provider 'other' meanwhile"})

    # E*Trade has its own /etrade/refresh route; this one ignores it.
    return RefreshResponse(updated=updated, skipped=skipped)


def _to_out(s) -> BalanceSnapshotOut:
    return BalanceSnapshotOut(
        id=s.id, broker=s.broker, asof=s.asof, equity_usd=s.equity_usd,
        cash_usd=s.cash_usd, buying_power=s.buying_power,
        unrealised_pnl=s.unrealised_pnl,
        realised_pnl_today=s.realised_pnl_today,
        source_note=s.source_note,
        created_at=s.created_at,
    )
