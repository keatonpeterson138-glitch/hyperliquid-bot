"""ETradeService — official E*Trade REST API via OAuth 1.0a.

The OAuth dance:

1. ``request_token()``  — consumer_key + consumer_secret → request_token +
   request_token_secret + authorize_url. User opens the authorize_url in a
   browser, logs in, and is shown a 5-character **verifier code**.
2. ``access_token(request_token, request_token_secret, verifier)`` →
   access_token + access_secret. These persist indefinitely unless the
   user revokes them.
3. ``list_accounts(access_token, access_secret)`` — returns every account
   on the login (often multiple: brokerage, IRA, 401k).
4. ``account_balance(account_id_key, access_token, access_secret)`` —
   equity + cash + margin for a single account.

Consumer key/secret come from the ``etrade`` provider in
``CredentialsStore``. Environment (sandbox vs prod) is read from
``metadata.sandbox`` (``true`` for sandbox).

We implement OAuth 1.0a signing by hand to avoid the ~5MB
``requests-oauthlib`` dep tree — the spec is just HMAC-SHA1 over a
normalized param string.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from backend.services.credentials_store import CredentialsStore

logger = logging.getLogger(__name__)


def _pct(s: str) -> str:
    """RFC 5849 percent-encoding — encodes everything except unreserved."""
    return quote(str(s), safe="-._~")


def _oauth_sign(method: str, url: str, params: dict[str, str],
                consumer_secret: str, token_secret: str = "") -> str:
    # Normalize params: sort by key, percent-encode both key and value,
    # then join by '&'. The reference impl is RFC 5849 §3.4.1.
    sorted_pairs = sorted((_pct(k), _pct(v)) for k, v in params.items())
    normalized = "&".join(f"{k}={v}" for k, v in sorted_pairs)
    base = f"{method.upper()}&{_pct(url)}&{_pct(normalized)}"
    key = f"{_pct(consumer_secret)}&{_pct(token_secret)}"
    sig = hmac.new(key.encode("utf-8"), base.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(sig).decode("ascii")


def _oauth_header(params: dict[str, str]) -> str:
    """Build the 'Authorization: OAuth ...' header from a params dict."""
    # OAuth spec: only oauth_* params go in the header; query/body params stay separate.
    oauth_only = {k: v for k, v in params.items() if k.startswith("oauth_")}
    pairs = ", ".join(f'{_pct(k)}="{_pct(v)}"' for k, v in sorted(oauth_only.items()))
    return f"OAuth {pairs}"


@dataclass
class ETradeConfig:
    consumer_key: str
    consumer_secret: str
    sandbox: bool
    host: str

    @property
    def api_host(self) -> str:
        return "https://apisb.etrade.com" if self.sandbox else "https://api.etrade.com"


class ETradeService:
    def __init__(self, credentials: CredentialsStore, *, timeout: float = 15.0) -> None:
        self._credentials = credentials
        self._client = httpx.Client(timeout=timeout)

    def _config(self) -> ETradeConfig:
        cred = self._credentials.first_for("etrade")
        if cred is None or not cred.api_key or not cred.api_secret:
            raise RuntimeError(
                "E*Trade needs API credentials — register an app at developer.etrade.com, "
                "then add provider 'etrade' in Sidebar → API Keys with "
                "api_key=<consumer key> + api_secret=<consumer secret>."
            )
        sandbox = bool((cred.metadata or {}).get("sandbox", False))
        return ETradeConfig(
            consumer_key=cred.api_key,
            consumer_secret=cred.api_secret,
            sandbox=sandbox,
            host="https://api.etrade.com",
        )

    def _oauth_base_params(self, consumer_key: str, token: str | None = None) -> dict[str, str]:
        params = {
            "oauth_consumer_key": consumer_key,
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp": str(int(time.time())),
            "oauth_nonce": secrets.token_hex(16),
            "oauth_version": "1.0",
        }
        if token:
            params["oauth_token"] = token
        return params

    # ── step 1: request token ─────────────────────────────────────

    def request_token(self) -> dict[str, str]:
        cfg = self._config()
        url = "https://api.etrade.com/oauth/request_token"
        params = self._oauth_base_params(cfg.consumer_key)
        params["oauth_callback"] = "oob"  # out-of-band: user gets verifier code manually
        sig = _oauth_sign("GET", url, params, cfg.consumer_secret)
        params["oauth_signature"] = sig
        resp = self._client.get(url, headers={"Authorization": _oauth_header(params)})
        if resp.status_code >= 400:
            raise RuntimeError(f"E*Trade request_token failed [{resp.status_code}]: {resp.text}")
        parsed = _parse_qs(resp.text)
        rt = parsed.get("oauth_token")
        rts = parsed.get("oauth_token_secret")
        if not rt or not rts:
            raise RuntimeError(f"E*Trade request_token returned malformed body: {resp.text}")
        authorize_url = f"https://us.etrade.com/e/t/etws/authorize?key={_pct(cfg.consumer_key)}&token={_pct(rt)}"
        return {
            "oauth_token": rt,
            "oauth_token_secret": rts,
            "authorize_url": authorize_url,
        }

    # ── step 2: access token ──────────────────────────────────────

    def access_token(self, request_token: str, request_token_secret: str, verifier: str) -> dict[str, str]:
        cfg = self._config()
        url = "https://api.etrade.com/oauth/access_token"
        params = self._oauth_base_params(cfg.consumer_key, token=request_token)
        params["oauth_verifier"] = verifier
        sig = _oauth_sign("GET", url, params, cfg.consumer_secret, token_secret=request_token_secret)
        params["oauth_signature"] = sig
        resp = self._client.get(url, headers={"Authorization": _oauth_header(params)})
        if resp.status_code >= 400:
            raise RuntimeError(f"E*Trade access_token failed [{resp.status_code}]: {resp.text}")
        parsed = _parse_qs(resp.text)
        at = parsed.get("oauth_token")
        ats = parsed.get("oauth_token_secret")
        if not at or not ats:
            raise RuntimeError(f"E*Trade access_token returned malformed body: {resp.text}")
        return {"oauth_token": at, "oauth_token_secret": ats}

    # ── step 3: authed API calls ──────────────────────────────────

    def _authed_get(self, url: str, access_token: str, access_secret: str,
                    query: dict[str, str] | None = None) -> dict[str, Any]:
        cfg = self._config()
        query = query or {}
        # Signing covers oauth_* + query params.
        sig_params = self._oauth_base_params(cfg.consumer_key, token=access_token)
        combined = {**sig_params, **query}
        sig = _oauth_sign("GET", url, combined, cfg.consumer_secret, token_secret=access_secret)
        sig_params["oauth_signature"] = sig
        headers = {
            "Authorization": _oauth_header(sig_params),
            "Accept": "application/json",
        }
        resp = self._client.get(url, headers=headers, params=query)
        if resp.status_code >= 400:
            raise RuntimeError(f"E*Trade GET {urlparse(url).path} failed [{resp.status_code}]: {resp.text}")
        try:
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"E*Trade GET {urlparse(url).path} returned non-JSON: {resp.text}") from exc

    def list_accounts(self, access_token: str, access_secret: str) -> list[dict[str, Any]]:
        cfg = self._config()
        url = f"{cfg.api_host}/v1/accounts/list"
        data = self._authed_get(url, access_token, access_secret)
        # Response path: AccountListResponse.Accounts.Account
        root = data.get("AccountListResponse") or {}
        accts = (root.get("Accounts") or {}).get("Account") or []
        if isinstance(accts, dict):
            accts = [accts]
        return accts

    def account_balance(self, account_id_key: str, access_token: str,
                        access_secret: str, account_type: str = "") -> dict[str, Any]:
        cfg = self._config()
        url = f"{cfg.api_host}/v1/accounts/{account_id_key}/balance"
        query = {"instType": "BROKERAGE", "realTimeNAV": "true"}
        if account_type:
            query["accountType"] = account_type
        data = self._authed_get(url, access_token, access_secret, query=query)
        return data.get("BalanceResponse") or {}


def _parse_qs(text: str) -> dict[str, str]:
    """Minimal parser for ``k=v&k=v`` — E*Trade returns oauth tokens this way."""
    out: dict[str, str] = {}
    for piece in text.strip().split("&"):
        if "=" not in piece:
            continue
        k, _, v = piece.partition("=")
        out[k] = v
    return out
