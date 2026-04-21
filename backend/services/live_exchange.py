"""LiveExchangeBridge — keeps a ``core.exchange.HyperliquidClient`` alive
once the vault is unlocked, and exposes it to the services that need to
place orders / close positions / read balance.

Why a bridge: the new FastAPI services (OrderService, KillSwitchService,
WalletService) are constructed at app startup, before any vault is
unlocked. Rebuilding them post-unlock is messy; instead each service
gets a reference to this singleton and reads the current live client
through it. On lock, the client is torn down and the services fall back
to their "pending local-only" stubs.

This is the same ``HyperliquidClient`` the legacy ``bot.py`` /
``dashboard.py`` used — no rewrite of the signing / order-flow logic.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)


class LiveExchangeBridge:
    """Holds the live client + settings. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._client: Any = None
        self._wallet_address: str | None = None
        self._testnet: bool = False

    # ── lifecycle ─────────────────────────────────────────────────

    def attach(self, *, private_key: str, wallet_address: str, testnet: bool = False) -> None:
        """Spin up a HyperliquidClient and cache it. Called from
        ``/vault/unlock`` once the key is back in memory."""
        # Lazy import so tests / packaging builds don't pull network deps.
        from core.exchange import HyperliquidClient

        with self._lock:
            if self._client is not None:
                self.detach()
            self._client = HyperliquidClient(
                private_key=private_key,
                wallet_address=wallet_address,
                testnet=testnet,
            )
            self._wallet_address = wallet_address
            self._testnet = testnet
        logger.info("live exchange attached: wallet=%s testnet=%s", wallet_address, testnet)

    def detach(self) -> None:
        """Tear down the live client. Called from ``/vault/lock``."""
        with self._lock:
            self._client = None
            self._wallet_address = None

    # ── reads ─────────────────────────────────────────────────────

    def is_live(self) -> bool:
        with self._lock:
            return self._client is not None

    def client(self) -> Any | None:
        """Returns the underlying ``HyperliquidClient``, or None if locked."""
        with self._lock:
            return self._client

    def require(self) -> Any:
        """Returns the client or raises — use from endpoints that need live."""
        c = self.client()
        if c is None:
            raise RuntimeError("vault locked — unlock via /vault/unlock first")
        return c

    def wallet_address(self) -> str | None:
        with self._lock:
            return self._wallet_address

    def testnet(self) -> bool:
        with self._lock:
            return self._testnet

    # ── BalanceProvider protocol (for WalletService) ──────────────

    def get_balance(self) -> dict[str, Any]:
        c = self.require()
        try:
            return c.get_balance() if hasattr(c, "get_balance") else {"usdc": 0.0}
        except Exception as exc:  # noqa: BLE001
            logger.warning("live balance fetch failed: %s", exc)
            return {}

    def get_all_positions(self) -> list[dict[str, Any]]:
        c = self.require()
        try:
            return c.get_all_positions() if hasattr(c, "get_all_positions") else []
        except Exception as exc:  # noqa: BLE001
            logger.warning("live positions fetch failed: %s", exc)
            return []

    # ── Order gateway shim — adapted to the OrderService.gateway shape ──

    def place_order(self, **kwargs: Any) -> dict[str, Any]:
        c = self.require()
        return c.place_order(**kwargs)

    def cancel_order(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        c = self.require()
        return c.cancel_order(*args, **kwargs)

    def close_position(self, symbol: str, dex: str = "") -> dict[str, Any]:
        c = self.require()
        if hasattr(c, "close_position"):
            return c.close_position(symbol, dex=dex)
        return {"symbol": symbol, "dex": dex, "skipped": True}

    def cancel_all(self) -> list[dict[str, Any]]:
        c = self.require()
        if hasattr(c, "cancel_all"):
            return c.cancel_all()
        return []
