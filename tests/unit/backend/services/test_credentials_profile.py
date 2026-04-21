"""Export/import round-trip for CredentialsStore."""
from __future__ import annotations

import json

import pytest

from backend.db.app_db import AppDB
from backend.services.credentials_store import CredentialsStore


@pytest.fixture
def store() -> CredentialsStore:
    db = AppDB(":memory:")
    yield CredentialsStore(db)
    db.close()


def test_export_includes_raw_values(store: CredentialsStore) -> None:
    store.create(provider="plaid", label="main",
                 api_key="CID_ABC", api_secret="SEC_XYZ",
                 metadata={"environment": "sandbox"})
    blob = store.export_profile()
    assert blob["version"] == 1
    assert len(blob["credentials"]) == 1
    # Export is plain-text (per the user's ask — local-only for now).
    entry = blob["credentials"][0]
    assert entry["api_key"] == "CID_ABC"
    assert entry["api_secret"] == "SEC_XYZ"
    assert entry["metadata"] == {"environment": "sandbox"}


def test_import_replace_wipes_existing(store: CredentialsStore) -> None:
    store.create(provider="fred", api_key="OLD_KEY")
    payload = {
        "version": 1,
        "credentials": [
            {"provider": "plaid", "label": "main", "api_key": "NEW_PLAID", "metadata": {}},
            {"provider": "etrade", "label": "live", "api_key": "NEW_ET", "api_secret": "ETSEC", "metadata": {}},
        ],
    }
    result = store.import_profile(payload, replace=True)
    assert result == {"created": 2, "updated": 0, "skipped": 0}
    got = store.list()
    providers = sorted(c.provider for c in got)
    assert providers == ["etrade", "plaid"]


def test_import_merge_updates_matching(store: CredentialsStore) -> None:
    existing = store.create(provider="plaid", label="main", api_key="OLD")
    payload = {
        "version": 1,
        "credentials": [
            # Same provider+label → must update existing.
            {"provider": "plaid", "label": "main", "api_key": "NEW", "api_secret": "NEW_SEC", "metadata": {"environment": "production"}},
            # Different label → fresh insert.
            {"provider": "plaid", "label": "dev", "api_key": "OTHER", "metadata": {"environment": "sandbox"}},
        ],
    }
    result = store.import_profile(payload, replace=False)
    assert result == {"created": 1, "updated": 1, "skipped": 0}

    refreshed = store.get(existing.id)
    assert refreshed is not None
    assert refreshed.api_key == "NEW"
    assert refreshed.api_secret == "NEW_SEC"
    assert refreshed.metadata == {"environment": "production"}

    all_labels = sorted(c.label for c in store.list())
    assert all_labels == ["dev", "main"]


def test_import_skips_unknown_providers(store: CredentialsStore) -> None:
    payload = {
        "version": 1,
        "credentials": [
            {"provider": "not-a-real-provider", "api_key": "X"},
            {"provider": "plaid", "api_key": "OK"},
        ],
    }
    result = store.import_profile(payload)
    assert result == {"created": 1, "updated": 0, "skipped": 1}


def test_import_rejects_malformed_payload(store: CredentialsStore) -> None:
    with pytest.raises(ValueError):
        store.import_profile({"no-credentials-key": True})
    with pytest.raises(ValueError):
        store.import_profile({"credentials": "not-a-list"})


def test_export_import_round_trip(store: CredentialsStore) -> None:
    store.create(provider="plaid", label="sbox",
                 api_key="P_ID", api_secret="P_SEC",
                 metadata={"environment": "sandbox"})
    store.create(provider="etrade", label="main",
                 api_key="E_CK", api_secret="E_CS",
                 metadata={"sandbox": True, "access_token": "AT", "access_secret": "AS"})
    store.create(provider="fred", api_key="F_KEY")

    blob = store.export_profile()
    serialized = json.dumps(blob)           # confirm the blob is JSON-clean
    reloaded = json.loads(serialized)

    # Wipe + restore.
    result = store.import_profile(reloaded, replace=True)
    assert result == {"created": 3, "updated": 0, "skipped": 0}

    after = {c.provider: c for c in store.list()}
    assert after["plaid"].api_key == "P_ID"
    assert after["plaid"].metadata == {"environment": "sandbox"}
    assert after["etrade"].api_secret == "E_CS"
    assert after["etrade"].metadata.get("access_token") == "AT"
    assert after["fred"].api_key == "F_KEY"
