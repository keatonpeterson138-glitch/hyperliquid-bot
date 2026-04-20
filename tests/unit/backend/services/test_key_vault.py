"""Tests for KeyVault — uses the in-memory keyring backend."""
from __future__ import annotations

import pytest

from backend.services.key_vault import (
    KeyVault,
    LockedError,
    install_in_memory_backend,
)


@pytest.fixture(autouse=True)
def memory_backend():
    install_in_memory_backend()
    yield


def test_store_and_unlock_roundtrip() -> None:
    vault = KeyVault()
    vault.store_key("0x" + "a" * 40, "private_key_hex")
    wallet = vault.unlock("0x" + "a" * 40)
    assert wallet == "0x" + "a" * 40
    assert vault.get_private_key() == "private_key_hex"
    assert vault.is_unlocked()


def test_unlock_without_wallet_uses_current() -> None:
    vault = KeyVault()
    vault.store_key("0x" + "b" * 40, "some_key")
    # No wallet_address arg — should pick the most recently stored one.
    wallet = vault.unlock()
    assert wallet == "0x" + "b" * 40


def test_unlock_without_prior_store_raises() -> None:
    vault = KeyVault()
    with pytest.raises(LockedError):
        vault.unlock()


def test_get_private_key_when_locked_raises() -> None:
    vault = KeyVault()
    with pytest.raises(LockedError):
        vault.get_private_key()


def test_lock_wipes_memory() -> None:
    vault = KeyVault()
    vault.store_key("0x" + "c" * 40, "key_xyz")
    vault.unlock("0x" + "c" * 40)
    assert vault.is_unlocked()
    vault.lock()
    assert not vault.is_unlocked()
    with pytest.raises(LockedError):
        vault.get_private_key()


def test_wipe_removes_from_keychain() -> None:
    vault = KeyVault()
    vault.store_key("0x" + "d" * 40, "removable")
    vault.wipe("0x" + "d" * 40)
    # Unlocking a wiped wallet raises because the keychain has no record.
    with pytest.raises(LockedError):
        vault.unlock("0x" + "d" * 40)


def test_wipe_non_existent_is_noop() -> None:
    vault = KeyVault()
    # Should not raise.
    vault.wipe("0x" + "e" * 40)


def test_multiple_wallets_coexist() -> None:
    vault = KeyVault()
    w1 = "0x" + "1" * 40
    w2 = "0x" + "2" * 40
    vault.store_key(w1, "key_one")
    vault.store_key(w2, "key_two")
    vault.unlock(w1)
    assert vault.get_private_key() == "key_one"
    vault.unlock(w2)
    assert vault.get_private_key() == "key_two"
