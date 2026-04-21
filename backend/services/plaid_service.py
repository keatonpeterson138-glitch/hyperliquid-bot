"""PlaidService — thin httpx wrapper for Plaid's REST API.

Plaid's Python SDK is a generated OpenAPI client ~50MB of transitive
deps; for the ~8 endpoints we need (Link token, exchange, accounts,
balance), direct httpx is lighter + debuggable. Credentials come from
the ``plaid`` provider in ``CredentialsStore``:

- ``api_key``     → PLAID_CLIENT_ID
- ``api_secret``  → PLAID_SECRET
- ``metadata.environment`` → 'sandbox' | 'production' (default sandbox)

If the user hasn't added a plaid credential, every method raises
``RuntimeError`` with a pointer back to the Sidebar → API Keys page.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from backend.services.credentials_store import CredentialsStore

logger = logging.getLogger(__name__)

PLAID_HOSTS = {
    "sandbox": "https://sandbox.plaid.com",
    "production": "https://production.plaid.com",
}


@dataclass
class PlaidConfig:
    client_id: str
    secret: str
    environment: str
    host: str


class PlaidService:
    def __init__(self, credentials: CredentialsStore, *, timeout: float = 15.0) -> None:
        self._credentials = credentials
        self._client = httpx.Client(timeout=timeout)

    def _config(self) -> PlaidConfig:
        cred = self._credentials.first_for("plaid")
        if cred is None or not cred.api_key or not cred.api_secret:
            raise RuntimeError(
                "Plaid needs an API key — add provider 'plaid' in Sidebar → API Keys "
                "with api_key=<PLAID_CLIENT_ID> + api_secret=<PLAID_SECRET>."
            )
        env = (cred.metadata or {}).get("environment", "sandbox").lower()
        if env not in PLAID_HOSTS:
            raise RuntimeError(f"Plaid metadata.environment must be one of {list(PLAID_HOSTS)}, got {env!r}")
        return PlaidConfig(
            client_id=cred.api_key,
            secret=cred.api_secret,
            environment=env,
            host=PLAID_HOSTS[env],
        )

    def _post(self, cfg: PlaidConfig, path: str, body: dict[str, Any]) -> dict[str, Any]:
        payload = {"client_id": cfg.client_id, "secret": cfg.secret, **body}
        resp = self._client.post(f"{cfg.host}{path}", json=payload)
        if resp.status_code >= 400:
            try:
                err = resp.json()
            except Exception:  # noqa: BLE001
                err = {"error_message": resp.text}
            raise RuntimeError(
                f"Plaid {path} failed: {err.get('error_code')} {err.get('error_message', resp.text)}"
            )
        return resp.json()

    def create_link_token(self, *, user_id: str, client_name: str = "Hyperliquid Bot",
                          products: list[str] | None = None,
                          country_codes: list[str] | None = None,
                          redirect_uri: str | None = None) -> dict[str, Any]:
        cfg = self._config()
        body: dict[str, Any] = {
            "user": {"client_user_id": user_id},
            "client_name": client_name,
            "products": products or ["auth", "transactions", "investments"],
            "country_codes": country_codes or ["US"],
            "language": "en",
        }
        if redirect_uri:
            body["redirect_uri"] = redirect_uri
        return self._post(cfg, "/link/token/create", body)

    def exchange_public_token(self, public_token: str) -> dict[str, Any]:
        cfg = self._config()
        return self._post(cfg, "/item/public_token/exchange", {"public_token": public_token})

    def item_get(self, access_token: str) -> dict[str, Any]:
        cfg = self._config()
        return self._post(cfg, "/item/get", {"access_token": access_token})

    def institutions_get_by_id(self, institution_id: str, country_codes: list[str] | None = None) -> dict[str, Any]:
        cfg = self._config()
        body = {
            "institution_id": institution_id,
            "country_codes": country_codes or ["US"],
        }
        return self._post(cfg, "/institutions/get_by_id", body)

    def accounts_get(self, access_token: str) -> dict[str, Any]:
        cfg = self._config()
        return self._post(cfg, "/accounts/get", {"access_token": access_token})

    def accounts_balance_get(self, access_token: str) -> dict[str, Any]:
        cfg = self._config()
        return self._post(cfg, "/accounts/balance/get", {"access_token": access_token})

    def investments_holdings_get(self, access_token: str) -> dict[str, Any]:
        cfg = self._config()
        return self._post(cfg, "/investments/holdings/get", {"access_token": access_token})

    def item_remove(self, access_token: str) -> dict[str, Any]:
        cfg = self._config()
        return self._post(cfg, "/item/remove", {"access_token": access_token})

    def sandbox_create_public_token(self, institution_id: str,
                                    initial_products: list[str] | None = None) -> dict[str, Any]:
        """Sandbox shortcut — creates a public_token without Plaid Link UI.
        Used in tests + the sandbox "quick link" button."""
        cfg = self._config()
        if cfg.environment != "sandbox":
            raise RuntimeError("sandbox_create_public_token only works in sandbox environment")
        return self._post(cfg, "/sandbox/public_token/create", {
            "institution_id": institution_id,
            "initial_products": initial_products or ["auth", "transactions"],
        })
