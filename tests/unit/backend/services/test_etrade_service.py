"""ETradeService — OAuth 1.0a signing + request/response shapes.

We don't want to hit E*Trade here. Instead, we verify that:
  * `_pct` percent-encodes per RFC 5849 (unreserved passthrough, rest encoded).
  * `_oauth_sign` produces a deterministic HMAC-SHA1 signature.
  * `_oauth_header` only includes ``oauth_*`` params, alphabetically sorted.
  * ``request_token`` / ``access_token`` / ``account_balance`` thread the
    right params through a mocked httpx.Client.
"""
from __future__ import annotations

from typing import Any

import pytest

from backend.db.app_db import AppDB
from backend.services.credentials_store import CredentialsStore
from backend.services.etrade_service import (
    ETradeService,
    _oauth_header,
    _oauth_sign,
    _parse_qs,
    _pct,
)


# ── unit tests for the signing helpers ─────────────────────────────

def test_pct_matches_rfc5849() -> None:
    # Unreserved set: A-Z / a-z / 0-9 / "-" / "." / "_" / "~" — passthrough.
    assert _pct("ABCxyz-._~") == "ABCxyz-._~"
    # Space → %20, slash → %2F, @ → %40.
    assert _pct("a b/c@d") == "a%20b%2Fc%40d"


def test_oauth_sign_is_deterministic() -> None:
    params = {
        "oauth_consumer_key": "CK",
        "oauth_token": "T",
        "oauth_nonce": "N",
        "oauth_timestamp": "1000",
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_version": "1.0",
    }
    sig1 = _oauth_sign("GET", "https://api.etrade.com/v1/accounts/list", params, "CS", "TS")
    sig2 = _oauth_sign("GET", "https://api.etrade.com/v1/accounts/list", params, "CS", "TS")
    assert sig1 == sig2
    assert len(sig1) == 28   # base64 of a 20-byte SHA1 digest


def test_oauth_header_filters_and_sorts() -> None:
    params = {
        "oauth_version": "1.0",
        "oauth_consumer_key": "CK",
        "foo": "bar",      # non-oauth → must not leak into the header
        "oauth_nonce": "N",
    }
    hdr = _oauth_header(params)
    assert hdr.startswith("OAuth ")
    assert "foo" not in hdr
    # Sorted order: consumer_key, nonce, version.
    idx_c = hdr.index("oauth_consumer_key")
    idx_n = hdr.index("oauth_nonce")
    idx_v = hdr.index("oauth_version")
    assert idx_c < idx_n < idx_v


def test_parse_qs_handles_etrade_response() -> None:
    body = "oauth_token=TOK&oauth_token_secret=SEC&oauth_callback_confirmed=true"
    parsed = _parse_qs(body)
    assert parsed == {
        "oauth_token": "TOK",
        "oauth_token_secret": "SEC",
        "oauth_callback_confirmed": "true",
    }


# ── service flow tests (mocked httpx client) ───────────────────────

class _FakeResponse:
    def __init__(self, status: int = 200, text: str = "", json_body: Any = None) -> None:
        self.status_code = status
        self._text = text
        self._json = json_body
    @property
    def text(self) -> str:
        return self._text
    def json(self) -> Any:
        if self._json is None:
            raise ValueError("no json")
        return self._json


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.responses: list[_FakeResponse] = []

    def get(self, url: str, headers: dict | None = None, params: dict | None = None) -> _FakeResponse:
        self.calls.append({"url": url, "headers": headers or {}, "params": params or {}})
        if not self.responses:
            raise AssertionError("no queued response for " + url)
        return self.responses.pop(0)


@pytest.fixture
def svc_with_creds() -> tuple[ETradeService, CredentialsStore]:
    db = AppDB(":memory:")
    creds = CredentialsStore(db)
    creds.create(provider="etrade", label="main",
                 api_key="CK", api_secret="CS",
                 metadata={"sandbox": False})
    svc = ETradeService(creds)
    yield svc, creds
    db.close()


def test_request_token_parses_and_builds_authorize_url(svc_with_creds) -> None:
    svc, _creds = svc_with_creds
    fake = _FakeClient()
    fake.responses.append(_FakeResponse(
        status=200, text="oauth_token=RT&oauth_token_secret=RTS&oauth_callback_confirmed=true",
    ))
    svc._client = fake  # type: ignore[assignment]

    result = svc.request_token()
    assert result["oauth_token"] == "RT"
    assert result["oauth_token_secret"] == "RTS"
    assert "authorize_url" in result
    assert "key=CK" in result["authorize_url"]
    assert "token=RT" in result["authorize_url"]

    # The request must carry an OAuth Authorization header with oauth_signature.
    call = fake.calls[0]
    assert "Authorization" in call["headers"]
    assert call["headers"]["Authorization"].startswith("OAuth ")
    assert "oauth_signature" in call["headers"]["Authorization"]
    assert "oauth_callback" in call["headers"]["Authorization"]


def test_access_token_exchanges_verifier(svc_with_creds) -> None:
    svc, _ = svc_with_creds
    fake = _FakeClient()
    fake.responses.append(_FakeResponse(
        status=200, text="oauth_token=AT&oauth_token_secret=ATS",
    ))
    svc._client = fake  # type: ignore[assignment]

    result = svc.access_token("RT", "RTS", "ABC12")
    assert result == {"oauth_token": "AT", "oauth_token_secret": "ATS"}
    # Verifier must be part of the signed header.
    hdr = fake.calls[0]["headers"]["Authorization"]
    assert "oauth_verifier" in hdr
    assert "ABC12" in hdr


def test_list_accounts_unwraps_response(svc_with_creds) -> None:
    svc, _ = svc_with_creds
    fake = _FakeClient()
    fake.responses.append(_FakeResponse(
        status=200, json_body={
            "AccountListResponse": {
                "Accounts": {
                    "Account": [
                        {"accountId": "123", "accountIdKey": "k1", "accountDesc": "Individual"},
                        {"accountId": "456", "accountIdKey": "k2", "accountDesc": "IRA"},
                    ],
                },
            },
        },
    ))
    svc._client = fake  # type: ignore[assignment]

    accts = svc.list_accounts("AT", "ATS")
    assert len(accts) == 2
    assert accts[0]["accountIdKey"] == "k1"


def test_request_token_raises_on_http_error(svc_with_creds) -> None:
    svc, _ = svc_with_creds
    fake = _FakeClient()
    fake.responses.append(_FakeResponse(status=401, text="oauth_problem=signature_invalid"))
    svc._client = fake  # type: ignore[assignment]
    with pytest.raises(RuntimeError, match="401"):
        svc.request_token()


def test_config_requires_credential() -> None:
    db = AppDB(":memory:")
    svc = ETradeService(CredentialsStore(db))
    with pytest.raises(RuntimeError, match="etrade"):
        svc._config()
    db.close()
