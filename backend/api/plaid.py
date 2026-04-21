"""/plaid — link accounts, manage items, feed the Balances refresh.

Flow the UI runs through:
1. User stores PLAID_CLIENT_ID + PLAID_SECRET in Sidebar → API Keys
   under provider='plaid' with metadata.environment='sandbox' | 'production'.
2. Frontend hits ``POST /plaid/link-token`` → gets a ``link_token`` →
   opens Plaid Link via react-plaid-link.
3. Plaid Link returns a ``public_token`` → frontend POSTs to
   ``/plaid/exchange`` → backend exchanges for an ``access_token``,
   persists the item + its accounts.
4. User toggles which accounts are ``tracked`` via ``PATCH /plaid/accounts/{id}``.
5. ``POST /balances/refresh`` (wired in balances.py) uses
   ``list_tracked_accounts()`` + ``accounts_balance_get`` to push a row
   per tracked account into the ``balances`` table.
"""
from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.services.plaid_service import PlaidService
from backend.services.plaid_store import PlaidStore

logger = logging.getLogger(__name__)

router = APIRouter(tags=["plaid"])


def get_plaid_service() -> PlaidService:
    raise HTTPException(status_code=503, detail="PlaidService not configured — add a 'plaid' API key first")


def get_plaid_store() -> PlaidStore:
    raise HTTPException(status_code=503, detail="PlaidStore not configured")


ServiceDep = Annotated[PlaidService, Depends(get_plaid_service)]
StoreDep = Annotated[PlaidStore, Depends(get_plaid_store)]


class LinkTokenRequest(BaseModel):
    client_name: str = "Hyperliquid Bot"
    products: list[str] = Field(default_factory=lambda: ["auth", "transactions", "investments"])
    country_codes: list[str] = Field(default_factory=lambda: ["US"])
    redirect_uri: str | None = None


class LinkTokenResponse(BaseModel):
    link_token: str
    expiration: str | None = None
    request_id: str | None = None


class ExchangeRequest(BaseModel):
    public_token: str


class ItemOut(BaseModel):
    id: str
    plaid_item_id: str
    institution_id: str | None = None
    institution_name: str | None = None
    environment: str


class AccountOut(BaseModel):
    id: str
    item_id: str
    plaid_account_id: str
    name: str | None = None
    official_name: str | None = None
    type: str | None = None
    subtype: str | None = None
    mask: str | None = None
    broker_label: str | None = None
    tracked: bool = True
    institution_name: str | None = None


class AccountUpdate(BaseModel):
    tracked: bool | None = None
    broker_label: str | None = None


class SandboxQuickLink(BaseModel):
    institution_id: str = "ins_109508"  # "First Platypus Bank" — Plaid's default sandbox ins
    initial_products: list[str] = Field(default_factory=lambda: ["auth", "transactions"])


@router.post("/plaid/link-token", response_model=LinkTokenResponse)
def create_link_token(req: LinkTokenRequest, svc: ServiceDep) -> LinkTokenResponse:
    try:
        data = svc.create_link_token(
            user_id=f"local-{uuid.uuid4().hex[:8]}",
            client_name=req.client_name,
            products=req.products,
            country_codes=req.country_codes,
            redirect_uri=req.redirect_uri,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return LinkTokenResponse(
        link_token=data["link_token"],
        expiration=data.get("expiration"),
        request_id=data.get("request_id"),
    )


@router.post("/plaid/exchange", response_model=ItemOut)
def exchange_public_token(req: ExchangeRequest, svc: ServiceDep, store: StoreDep) -> ItemOut:
    """Exchange a Plaid Link public_token → access_token, persist the
    item, and pull its accounts."""
    try:
        exch = svc.exchange_public_token(req.public_token)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    access_token = exch["access_token"]
    plaid_item_id = exch["item_id"]

    # Pull institution metadata (optional — fail soft if the call errors).
    institution_id: str | None = None
    institution_name: str | None = None
    try:
        item_info = svc.item_get(access_token)
        institution_id = (item_info.get("item") or {}).get("institution_id")
        if institution_id:
            ins = svc.institutions_get_by_id(institution_id)
            institution_name = (ins.get("institution") or {}).get("name")
    except RuntimeError as exc:
        logger.warning("plaid /item/get or /institutions/get_by_id failed: %s", exc)

    cfg_env = svc._config().environment
    item = store.add_item(
        plaid_item_id=plaid_item_id,
        access_token=access_token,
        institution_id=institution_id,
        institution_name=institution_name,
        environment=cfg_env,
    )

    # Pull accounts for the new item so the UI has something to render.
    try:
        accts = svc.accounts_get(access_token).get("accounts", [])
    except RuntimeError as exc:
        logger.warning("plaid /accounts/get failed for new item: %s", exc)
        accts = []

    for a in accts:
        subtype = a.get("subtype") or ""
        atype = a.get("type") or ""
        broker_label = _infer_broker_label(institution_name, atype, subtype)
        store.upsert_account(
            item_id=item.id,
            plaid_account_id=a["account_id"],
            name=a.get("name"),
            official_name=a.get("official_name"),
            type=atype,
            subtype=subtype,
            mask=a.get("mask"),
            broker_label=broker_label,
            tracked=atype in {"investment", "brokerage"} or subtype in {"brokerage", "ira", "401k", "cash management"},
        )

    return _item_to_out(item)


@router.get("/plaid/items", response_model=list[ItemOut])
def list_items(store: StoreDep) -> list[ItemOut]:
    return [_item_to_out(i) for i in store.list_items()]


@router.delete("/plaid/items/{iid}", status_code=204)
def delete_item(iid: str, svc: ServiceDep, store: StoreDep) -> None:
    item = store.get_item(iid)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    try:
        svc.item_remove(item.access_token)
    except RuntimeError as exc:
        logger.warning("plaid /item/remove failed (continuing with local delete): %s", exc)
    store.delete_item(iid)


@router.get("/plaid/accounts", response_model=list[AccountOut])
def list_accounts(store: StoreDep) -> list[AccountOut]:
    return [_account_to_out(a) for a in store.list_accounts()]


@router.patch("/plaid/accounts/{aid}", response_model=AccountOut)
def update_account(aid: str, req: AccountUpdate, store: StoreDep) -> AccountOut:
    if req.tracked is not None:
        store.set_tracked(aid, req.tracked)
    if req.broker_label is not None:
        store.set_broker_label(aid, req.broker_label)
    got = store.get_account(aid)
    if got is None:
        raise HTTPException(status_code=404, detail="account not found")
    return _account_to_out(got)


@router.post("/plaid/sandbox/quick-link", response_model=ItemOut)
def sandbox_quick_link(req: SandboxQuickLink, svc: ServiceDep, store: StoreDep) -> ItemOut:
    """Sandbox-only: bypass the Link UI with an auto-generated public_token.
    Useful for E2E testing and quick validation without cycling through the
    web SDK."""
    try:
        got = svc.sandbox_create_public_token(req.institution_id, req.initial_products)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    public_token = got["public_token"]
    return exchange_public_token(ExchangeRequest(public_token=public_token), svc, store)


def _infer_broker_label(institution_name: str | None, atype: str, subtype: str) -> str:
    """Best-effort map institution + account type → the enum in
    ``SUPPORTED_BROKERS``. User can override via PATCH /plaid/accounts/{id}."""
    name = (institution_name or "").lower()
    if "fidelity" in name:
        return "fidelity"
    if "robinhood" in name:
        return "robinhood"
    if "e*trade" in name or "etrade" in name:
        return "etrade"
    if "schwab" in name or "tda" in name or "td ameritrade" in name:
        return "schwab"
    if "coinbase" in name:
        return "coinbase"
    if "kraken" in name:
        return "kraken"
    if atype == "investment" or subtype in {"brokerage", "ira", "401k"}:
        return "other"
    return "other"


def _item_to_out(item) -> ItemOut:
    return ItemOut(
        id=item.id, plaid_item_id=item.plaid_item_id,
        institution_id=item.institution_id,
        institution_name=item.institution_name,
        environment=item.environment,
    )


def _account_to_out(a) -> AccountOut:
    return AccountOut(
        id=a.id, item_id=a.item_id, plaid_account_id=a.plaid_account_id,
        name=a.name, official_name=a.official_name,
        type=a.type, subtype=a.subtype, mask=a.mask,
        broker_label=a.broker_label, tracked=a.tracked,
        institution_name=a.institution_name,
    )
