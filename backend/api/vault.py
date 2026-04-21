"""/vault — OS-keychain-backed key storage for the trading bot.

``/vault/unlock`` reaches into the OS keychain, pulls the stored private
key into memory, and **attaches a live HyperliquidClient** via the
``LiveExchangeBridge`` so the OrderService / KillSwitchService /
WalletService can now actually trade. ``/vault/lock`` tears it back down.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.services.key_vault import KeyVault, LockedError
from backend.services.live_exchange import LiveExchangeBridge
from backend.services.settings_store import SettingsStore

router = APIRouter(tags=["vault"])


def get_vault() -> KeyVault:
    raise HTTPException(status_code=503, detail="KeyVault not configured")


def get_settings_for_vault() -> SettingsStore | None:
    # Optional — tests + degraded modes can skip settings persistence.
    return None


VaultDep = Annotated[KeyVault, Depends(get_vault)]
SettingsDep = Annotated["SettingsStore | None", Depends(get_settings_for_vault)]


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
def unlock(
    req: UnlockRequest,
    vault: VaultDep,
    settings: SettingsDep,
    request: Request,
) -> UnlockResponse:
    try:
        wallet = vault.unlock(req.wallet_address)
    except LockedError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # Bridge to live — construct the HyperliquidClient and persist the
    # wallet address on settings so /wallet/* endpoints can resolve it
    # without the caller passing it every time.
    bridge: LiveExchangeBridge | None = getattr(request.app.state, "live_exchange", None)
    if bridge is not None:
        try:
            pk = vault.get_private_key()
            bridge.attach(
                private_key=pk,
                wallet_address=wallet,
                testnet=bool(settings.all().testnet) if settings is not None else False,
            )
        except Exception as exc:  # noqa: BLE001
            # Log but don't fail the unlock — user can retry.
            import logging
            logging.getLogger(__name__).warning("live exchange attach failed: %s", exc)

    # Persist the master address for read-only /wallet/positions queries.
    if settings is not None:
        settings.update({"extras": {"wallet_address": wallet}})

    return UnlockResponse(unlocked_at=datetime.now(UTC), wallet_address=wallet)


@router.post("/vault/lock", status_code=204)
def lock_vault(vault: VaultDep, request: Request) -> None:
    vault.lock()
    bridge: LiveExchangeBridge | None = getattr(request.app.state, "live_exchange", None)
    if bridge is not None:
        bridge.detach()


@router.get("/vault/status", response_model=StatusResponse)
def status(vault: VaultDep) -> StatusResponse:
    return StatusResponse(unlocked=vault.is_unlocked(), wallet_address=vault.unlocked_wallet())


class WipeRequest(BaseModel):
    wallet_address: str


@router.delete("/vault/wipe", status_code=204)
def wipe(req: WipeRequest, vault: VaultDep) -> None:
    vault.wipe(req.wallet_address)
