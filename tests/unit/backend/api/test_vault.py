"""API tests for /vault."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api import vault as vault_api
from backend.main import create_app
from backend.services.key_vault import KeyVault, install_in_memory_backend


@pytest.fixture(autouse=True)
def memory_backend():
    install_in_memory_backend()
    yield


def _client() -> tuple[TestClient, KeyVault]:
    vault = KeyVault()
    app = create_app()
    app.dependency_overrides[vault_api.get_vault] = lambda: vault
    return TestClient(app), vault


def test_store_then_unlock_then_status() -> None:
    client, _ = _client()
    wallet = "0x" + "a" * 40

    resp = client.post("/vault/store", json={"wallet_address": wallet, "private_key": "KEY"})
    assert resp.status_code == 204

    resp = client.post("/vault/unlock", json={"wallet_address": wallet})
    assert resp.status_code == 200
    assert resp.json()["wallet_address"] == wallet

    resp = client.get("/vault/status")
    assert resp.json() == {"unlocked": True, "wallet_address": wallet}


def test_lock_clears_status() -> None:
    client, _ = _client()
    wallet = "0x" + "b" * 40
    client.post("/vault/store", json={"wallet_address": wallet, "private_key": "K"})
    client.post("/vault/unlock", json={"wallet_address": wallet})
    resp = client.post("/vault/lock")
    assert resp.status_code == 204
    assert client.get("/vault/status").json() == {"unlocked": False, "wallet_address": None}


def test_unlock_unknown_wallet_404() -> None:
    client, _ = _client()
    resp = client.post("/vault/unlock", json={"wallet_address": "0x" + "9" * 40})
    assert resp.status_code == 404


def test_store_rejects_bad_wallet_format() -> None:
    client, _ = _client()
    resp = client.post("/vault/store", json={"wallet_address": "not_an_addr", "private_key": "k"})
    assert resp.status_code == 422


def test_wipe() -> None:
    client, _ = _client()
    wallet = "0x" + "c" * 40
    client.post("/vault/store", json={"wallet_address": wallet, "private_key": "K"})
    resp = client.request("DELETE", "/vault/wipe", json={"wallet_address": wallet})
    assert resp.status_code == 204
    assert client.post("/vault/unlock", json={"wallet_address": wallet}).status_code == 404
