"""Tests for ExposureCapService + SettingsStore."""
from __future__ import annotations

import json

import pytest

from backend.services.exposure_cap import ExposureCapService
from backend.services.settings_store import SettingsStore


def test_cap_allows_within_ceiling() -> None:
    svc = ExposureCapService(cap_usd=1_000)
    result = svc.check(prospective_size_usd=200, open_positions=[{"size_usd": 500}])
    assert result.allowed
    assert result.current_exposure_usd == 500
    assert result.headroom_usd == 500


def test_cap_blocks_over_ceiling() -> None:
    svc = ExposureCapService(cap_usd=1_000)
    result = svc.check(prospective_size_usd=600, open_positions=[{"size_usd": 500}])
    assert not result.allowed
    assert "cap exceeded" in result.reason


def test_cap_unbounded_default() -> None:
    svc = ExposureCapService()
    result = svc.check(prospective_size_usd=1e9, open_positions=[])
    assert result.allowed


def test_cap_set_cap_rejects_negative() -> None:
    svc = ExposureCapService()
    with pytest.raises(ValueError):
        svc.set_cap(-1)


def test_settings_default(tmp_path) -> None:
    store = SettingsStore(path=tmp_path / "settings.json")
    s = store.all()
    assert s.theme == "dark"
    assert s.testnet is True


def test_settings_patch_roundtrip(tmp_path) -> None:
    path = tmp_path / "settings.json"
    store = SettingsStore(path=path)
    store.update({"theme": "light", "confirm_above_usd": 500.0})
    # Reload from disk
    store2 = SettingsStore(path=path)
    assert store2.all().theme == "light"
    assert store2.all().confirm_above_usd == 500.0


def test_settings_patch_extras_pocket(tmp_path) -> None:
    store = SettingsStore(path=tmp_path / "s.json")
    store.update({"custom_key": "hello"})
    assert store.all().extras["custom_key"] == "hello"


def test_settings_handles_corrupt_file(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{not json")
    store = SettingsStore(path=path)
    # Falls back to defaults rather than raising
    assert store.all().theme == "dark"


def test_settings_writes_valid_json(tmp_path) -> None:
    path = tmp_path / "settings.json"
    store = SettingsStore(path=path)
    store.update({"theme": "light"})
    data = json.loads(path.read_text())
    assert data["theme"] == "light"
