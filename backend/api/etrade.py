"""/etrade — OAuth 1.0a link flow + balance refresh.

UX in the Balances page:
1. "Connect E*Trade" → ``POST /etrade/link-start`` → response contains
   ``authorize_url``. Frontend opens it in a browser.
2. User logs into E*Trade, confirms access, receives a 5-char verifier code.
3. User pastes it back → ``POST /etrade/link-complete {verifier}`` →
   backend exchanges for access_token + access_secret, saves them on the
   ``etrade`` credential's metadata.
4. ``POST /etrade/refresh`` → iterates every ``tracked`` account and pushes
   a ``balances`` row per account.

Access tokens for E*Trade last until the user logs out of the E*Trade
session, or about 2 hours of inactivity — the UI can prompt a re-auth on
401 from the refresh call.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.services.balances_store import BalancesStore
from backend.services.credentials_store import CredentialsStore
from backend.services.etrade_service import ETradeService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["etrade"])


def get_etrade_service() -> ETradeService:
    raise HTTPException(status_code=503, detail="ETradeService not configured")


def get_etrade_credentials() -> CredentialsStore:
    raise HTTPException(status_code=503, detail="CredentialsStore not configured")


def get_etrade_balances_store() -> BalancesStore:
    raise HTTPException(status_code=503, detail="BalancesStore not configured")


ServiceDep = Annotated[ETradeService, Depends(get_etrade_service)]
CredsDep = Annotated[CredentialsStore, Depends(get_etrade_credentials)]
BalancesDep = Annotated[BalancesStore, Depends(get_etrade_balances_store)]


class LinkStartResponse(BaseModel):
    authorize_url: str
    request_token: str
    request_token_secret: str
    note: str = (
        "Open authorize_url in a browser, sign in, and copy the 5-char verifier code. "
        "Then POST it to /etrade/link-complete along with request_token + request_token_secret."
    )


class LinkCompleteRequest(BaseModel):
    request_token: str
    request_token_secret: str
    verifier: str


class SessionStatus(BaseModel):
    connected: bool
    sandbox: bool = False
    accounts: list[dict[str, Any]] = Field(default_factory=list)
    last_refreshed_at: str | None = None


class RefreshResponse(BaseModel):
    snapshots: list[dict[str, Any]] = Field(default_factory=list)
    skipped: list[dict[str, str]] = Field(default_factory=list)


@router.post("/etrade/link-start", response_model=LinkStartResponse)
def link_start(svc: ServiceDep) -> LinkStartResponse:
    try:
        data = svc.request_token()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return LinkStartResponse(
        authorize_url=data["authorize_url"],
        request_token=data["oauth_token"],
        request_token_secret=data["oauth_token_secret"],
    )


@router.post("/etrade/link-complete", response_model=SessionStatus)
def link_complete(req: LinkCompleteRequest, svc: ServiceDep, creds: CredsDep) -> SessionStatus:
    try:
        tok = svc.access_token(req.request_token, req.request_token_secret, req.verifier)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    cred = creds.first_for("etrade")
    if cred is None:
        raise HTTPException(status_code=400, detail="etrade credential missing — re-enter consumer key/secret")

    metadata = dict(cred.metadata or {})
    metadata["access_token"] = tok["oauth_token"]
    metadata["access_secret"] = tok["oauth_token_secret"]

    # Pull accounts so the UI has something to render immediately.
    try:
        accounts = svc.list_accounts(tok["oauth_token"], tok["oauth_token_secret"])
    except RuntimeError as exc:
        logger.warning("etrade list_accounts failed: %s", exc)
        accounts = []

    # Summarize only what we need — the raw blob is too verbose.
    metadata["accounts"] = [
        {
            "accountId": a.get("accountId"),
            "accountIdKey": a.get("accountIdKey"),
            "accountDesc": a.get("accountDesc"),
            "accountType": a.get("accountType"),
            "institutionType": a.get("institutionType"),
            "tracked": True,
        }
        for a in accounts
        if a.get("accountIdKey")
    ]

    creds.update(cred.id, metadata=metadata)
    return SessionStatus(
        connected=True,
        sandbox=bool(metadata.get("sandbox", False)),
        accounts=metadata["accounts"],
        last_refreshed_at=metadata.get("last_refreshed_at"),
    )


@router.get("/etrade/session", response_model=SessionStatus)
def session(creds: CredsDep) -> SessionStatus:
    cred = creds.first_for("etrade")
    if cred is None:
        return SessionStatus(connected=False)
    meta = cred.metadata or {}
    return SessionStatus(
        connected=bool(meta.get("access_token") and meta.get("access_secret")),
        sandbox=bool(meta.get("sandbox", False)),
        accounts=meta.get("accounts") or [],
        last_refreshed_at=meta.get("last_refreshed_at"),
    )


@router.delete("/etrade/session", status_code=204)
def disconnect(creds: CredsDep) -> None:
    cred = creds.first_for("etrade")
    if cred is None:
        return
    meta = dict(cred.metadata or {})
    for k in ("access_token", "access_secret", "accounts", "last_refreshed_at"):
        meta.pop(k, None)
    creds.update(cred.id, metadata=meta)


class AccountTrack(BaseModel):
    accountIdKey: str
    tracked: bool


@router.patch("/etrade/accounts", response_model=SessionStatus)
def update_account_track(req: AccountTrack, creds: CredsDep) -> SessionStatus:
    cred = creds.first_for("etrade")
    if cred is None:
        raise HTTPException(status_code=404, detail="no etrade credential")
    meta = dict(cred.metadata or {})
    accounts = list(meta.get("accounts") or [])
    for a in accounts:
        if a.get("accountIdKey") == req.accountIdKey:
            a["tracked"] = req.tracked
            break
    meta["accounts"] = accounts
    creds.update(cred.id, metadata=meta)
    return SessionStatus(
        connected=bool(meta.get("access_token")),
        sandbox=bool(meta.get("sandbox", False)),
        accounts=accounts,
        last_refreshed_at=meta.get("last_refreshed_at"),
    )


@router.post("/etrade/refresh", response_model=RefreshResponse)
def refresh(svc: ServiceDep, creds: CredsDep, balances: BalancesDep) -> RefreshResponse:
    """Pull balances for every tracked E*Trade account and record snapshots."""
    cred = creds.first_for("etrade")
    if cred is None:
        raise HTTPException(status_code=404, detail="no etrade credential")
    meta = dict(cred.metadata or {})
    access_token = meta.get("access_token")
    access_secret = meta.get("access_secret")
    if not access_token or not access_secret:
        raise HTTPException(status_code=400, detail="etrade not linked — call /etrade/link-start first")

    snapshots: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    equity_total = 0.0
    cash_total = 0.0
    raw_accounts: list[dict[str, Any]] = []

    for acct in meta.get("accounts") or []:
        if not acct.get("tracked"):
            skipped.append({"account": acct.get("accountDesc") or acct.get("accountId") or "?", "reason": "not tracked"})
            continue
        try:
            bal = svc.account_balance(
                acct["accountIdKey"],
                access_token, access_secret,
                account_type=acct.get("accountType") or "",
            )
        except RuntimeError as exc:
            skipped.append({
                "account": acct.get("accountDesc") or acct.get("accountId") or "?",
                "reason": str(exc),
            })
            continue
        computed = bal.get("Computed") or {}
        total_value = (computed.get("RealTimeValues") or {}).get("totalAccountValue")
        cash_balance = computed.get("cashBalance") or (computed.get("RealTimeValues") or {}).get("netMv")
        if total_value is not None:
            equity_total += float(total_value)
            raw_accounts.append({
                "accountId": acct.get("accountId"),
                "accountDesc": acct.get("accountDesc"),
                "totalAccountValue": total_value,
                "cashBalance": cash_balance,
            })
            snapshots.append({
                "accountId": acct.get("accountId"),
                "accountDesc": acct.get("accountDesc"),
                "totalAccountValue": total_value,
                "cashBalance": cash_balance,
            })
        if cash_balance is not None:
            try:
                cash_total += float(cash_balance)
            except (TypeError, ValueError):
                pass

    if equity_total > 0 or raw_accounts:
        try:
            balances.record(
                broker="etrade",
                equity_usd=equity_total,
                cash_usd=cash_total or None,
                source_note="etrade-oauth",
                raw={"accounts": raw_accounts},
            )
        except ValueError as exc:
            skipped.append({"account": "etrade-aggregate", "reason": str(exc)})

    # Stamp last_refreshed_at on the credential so the UI can show recency.
    from datetime import UTC, datetime
    meta["last_refreshed_at"] = datetime.now(UTC).isoformat()
    creds.update(cred.id, metadata=meta)

    return RefreshResponse(snapshots=snapshots, skipped=skipped)
