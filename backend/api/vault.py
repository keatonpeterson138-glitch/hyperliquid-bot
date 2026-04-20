"""/vault — OS-keychain-backed key storage for the trading bot."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.services.key_vault import KeyVault, LockedError

router = APIRouter(tags=["vault"])


def get_vault() -> KeyVault:
    raise HTTPException(status_code=503, detail="KeyVault not configured")


VaultDep = Annotated[KeyVault, Depends(get_vault)]


class StoreRequest(BaseModel):
    wallet_address: str = Field(..., pattern=r"^0x[a-fA-F0-9]{40}$")
    private_key: str = Field(..., min_length=1)


class UnlockRequest(BaseModel):
    wallet_address: str | None = None


class UnlockResponse(BaseModel):
    unlocked_at: datetime
    wallet_address: str


class StatusResponse(BaseModel):
    unlocked: bool
    wallet_address: str | None = None


@router.post("/vault/store", status_code=204)
def store_key(req: StoreRequest, vault: VaultDep) -> None:
    vault.store_key(req.wallet_address, req.private_key)


@router.post("/vault/unlock", response_model=UnlockResponse)
def unlock(req: UnlockRequest, vault: VaultDep) -> UnlockResponse:
    try:
        wallet = vault.unlock(req.wallet_address)
    except LockedError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return UnlockResponse(unlocked_at=datetime.now(UTC), wallet_address=wallet)


@router.post("/vault/lock", status_code=204)
def lock_vault(vault: VaultDep) -> None:
    vault.lock()


@router.get("/vault/status", response_model=StatusResponse)
def status(vault: VaultDep) -> StatusResponse:
    return StatusResponse(unlocked=vault.is_unlocked(), wallet_address=vault.unlocked_wallet())


class WipeRequest(BaseModel):
    wallet_address: str


@router.delete("/vault/wipe", status_code=204)
def wipe(req: WipeRequest, vault: VaultDep) -> None:
    vault.wipe(req.wallet_address)
