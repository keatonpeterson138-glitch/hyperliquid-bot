"""/credentials — CRUD for third-party API keys.

Every response masks the key/secret — the raw value never leaves the
process once stored. Hyperliquid private keys do NOT go here; they live
in the OS keychain via ``/vault`` + KeyVault.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.services.credentials_store import CredentialsStore

router = APIRouter(tags=["credentials"])


def get_credentials_store() -> CredentialsStore:
    raise HTTPException(status_code=503, detail="CredentialsStore not configured")


StoreDep = Annotated[CredentialsStore, Depends(get_credentials_store)]


class CredentialOut(BaseModel):
    id: str
    provider: str
    label: str | None = None
    api_key: str | None = None         # masked
    api_secret: str | None = None      # masked
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CredentialCreate(BaseModel):
    provider: str
    label: str | None = None
    api_key: str | None = None
    api_secret: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CredentialUpdate(BaseModel):
    label: str | None = None
    api_key: str | None = None
    api_secret: str | None = None
    metadata: dict[str, Any] | None = None


@router.get("/credentials", response_model=list[CredentialOut])
def list_credentials(store: StoreDep, provider: str | None = None) -> list[CredentialOut]:
    return [_to_out(c.masked()) for c in store.list(provider=provider)]


@router.post("/credentials", response_model=CredentialOut)
def create_credential(req: CredentialCreate, store: StoreDep) -> CredentialOut:
    try:
        cred = store.create(
            provider=req.provider, label=req.label,
            api_key=req.api_key, api_secret=req.api_secret, metadata=req.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_out(cred.masked())


@router.patch("/credentials/{cid}", response_model=CredentialOut)
def update_credential(cid: str, req: CredentialUpdate, store: StoreDep) -> CredentialOut:
    cred = store.update(
        cid, label=req.label, api_key=req.api_key,
        api_secret=req.api_secret, metadata=req.metadata,
    )
    if cred is None:
        raise HTTPException(status_code=404, detail=f"Credential not found: {cid}")
    return _to_out(cred.masked())


@router.delete("/credentials/{cid}", status_code=204)
def delete_credential(cid: str, store: StoreDep) -> None:
    store.delete(cid)


class ImportRequest(BaseModel):
    payload: dict[str, Any]
    replace: bool = False


class ImportResult(BaseModel):
    created: int = 0
    updated: int = 0
    skipped: int = 0


@router.get("/credentials/export")
def export_profile(store: StoreDep) -> dict[str, Any]:
    """Dump every credential with raw values — used by the Settings
    "Export API keys" button. The response body IS the file content the
    UI writes to disk."""
    return store.export_profile()


@router.post("/credentials/import", response_model=ImportResult)
def import_profile(req: ImportRequest, store: StoreDep) -> ImportResult:
    try:
        result = store.import_profile(req.payload, replace=req.replace)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ImportResult(**result)


def _to_out(cred) -> CredentialOut:
    return CredentialOut(
        id=cred.id, provider=cred.provider, label=cred.label,
        api_key=cred.api_key, api_secret=cred.api_secret,
        metadata=cred.metadata,
        created_at=cred.created_at, updated_at=cred.updated_at,
    )
