"""KeyVault — OS-keychain-backed secret storage for private keys.

Wraps the ``keyring`` library so keys never touch disk unencrypted.
Uses platform backends:
- Windows: Credential Manager
- macOS: Keychain
- Linux: libsecret (GNOME Keyring / KWallet via DBus)

Tests + CI inject an in-memory fake via ``install_backend()`` so no OS
keychain is needed.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

try:
    import keyring
    import keyring.errors
except ImportError:  # pragma: no cover — optional, tests set a fake
    keyring = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_SERVICE_NAME = "hyperliquid-bot"
_WALLET_REGISTRY_KEY = "__current_wallet__"


class LockedError(RuntimeError):
    """Raised when get_private_key() is called before unlock()."""


class KeyVault:
    """Single-operator key vault.

    Lifecycle:
        1. ``store_key(wallet, key)``     — writes to OS keychain.
        2. On app launch: ``unlock(wallet)`` loads the key into memory.
        3. Trade engine calls ``get_private_key()`` to sign orders.
        4. ``lock()`` (on idle or exit) wipes the in-memory copy.
    """

    def __init__(self, service_name: str = _SERVICE_NAME) -> None:
        self.service_name = service_name
        self._unlocked_wallet: str | None = None
        self._unlocked_key: str | None = None
        self._lock = threading.RLock()

    # ── Storage ────────────────────────────────────────────────────────────

    def store_key(self, wallet_address: str, private_key: str) -> None:
        """Persist a wallet+key to the OS keychain. Also records the wallet
        as the "current" one so ``unlock()`` can be called with no args."""
        _require_keyring()
        with self._lock:
            keyring.set_password(self.service_name, wallet_address, private_key)
            keyring.set_password(self.service_name, _WALLET_REGISTRY_KEY, wallet_address)

    def wipe(self, wallet_address: str) -> None:
        """Delete a wallet's key from the keychain."""
        _require_keyring()
        with self._lock:
            try:
                keyring.delete_password(self.service_name, wallet_address)
            except keyring.errors.PasswordDeleteError:
                pass

    # ── Lock / unlock ──────────────────────────────────────────────────────

    def unlock(self, wallet_address: str | None = None) -> str:
        """Pull a key out of the OS keychain into memory; returns the wallet address."""
        _require_keyring()
        with self._lock:
            if wallet_address is None:
                wallet_address = keyring.get_password(self.service_name, _WALLET_REGISTRY_KEY)
                if not wallet_address:
                    raise LockedError("No wallet configured; call store_key() first.")

            key = keyring.get_password(self.service_name, wallet_address)
            if not key:
                raise LockedError(f"No key stored for wallet {wallet_address}.")

            self._unlocked_wallet = wallet_address
            self._unlocked_key = key
            logger.info("KeyVault unlocked for wallet %s", _redact(wallet_address))
            return wallet_address

    def lock(self) -> None:
        with self._lock:
            self._unlocked_wallet = None
            self._unlocked_key = None

    def is_unlocked(self) -> bool:
        with self._lock:
            return self._unlocked_key is not None

    def unlocked_wallet(self) -> str | None:
        with self._lock:
            return self._unlocked_wallet

    def get_private_key(self) -> str:
        with self._lock:
            if self._unlocked_key is None:
                raise LockedError("KeyVault is locked; call unlock() first.")
            return self._unlocked_key


# ── Module-level fake backend for tests ────────────────────────────────────


class InMemoryKeyringBackend:
    """``keyring`` Backend substitute that stores in-process only.

    Install with ``keyring.set_keyring(InMemoryKeyringBackend())`` in
    conftest / fixtures. Not threadsafe across processes — by design.
    """

    priority = 99  # higher than any real backend so test wins

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], str] = {}

    def set_password(self, servicename: str, username: str, password: str) -> None:
        self._store[(servicename, username)] = password

    def get_password(self, servicename: str, username: str) -> str | None:
        return self._store.get((servicename, username))

    def delete_password(self, servicename: str, username: str) -> None:
        if (servicename, username) not in self._store:
            raise keyring.errors.PasswordDeleteError(f"not found: {username}")
        del self._store[(servicename, username)]


def install_in_memory_backend() -> InMemoryKeyringBackend:
    """Install + return a fresh in-memory backend for tests/dev."""
    _require_keyring()
    backend = InMemoryKeyringBackend()
    keyring.set_keyring(backend)
    return backend


def _require_keyring() -> None:
    if keyring is None:
        raise RuntimeError(
            "python-keyring is not installed. Add it to requirements.txt "
            "or install an in-memory backend for tests."
        )


def _redact(value: str) -> str:
    if not value:
        return value
    if len(value) <= 10:
        return value[:2] + "…" + value[-2:]
    return value[:6] + "…" + value[-4:]


# Convenience re-export: modules that want the type but not the optional
# keyring import can ``from backend.services.key_vault import KeyVault, LockedError``.
__all__ = ["KeyVault", "LockedError", "InMemoryKeyringBackend", "install_in_memory_backend"]


# Silence unused-import in type-hint contexts.
_: Any = None
