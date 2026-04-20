"""Tests for UniverseManager — fake Info + OutcomeClient, no network."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from backend.db.app_db import AppDB
from backend.services.universe_manager import UniverseManager


@dataclass
class FakeInfo:
    responses: dict[str, dict[str, Any]] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def meta(self, dex: str = "") -> dict[str, Any]:
        self.calls.append(dex)
        return self.responses.get(dex, {"universe": []})


@dataclass
class FakeOutcomeClient:
    markets: list[dict[str, Any]] = field(default_factory=list)

    def list_markets(self) -> list[dict[str, Any]]:
        return list(self.markets)


@pytest.fixture
def db() -> AppDB:
    db = AppDB(":memory:")
    yield db
    db.close()


def _info_with_btc_and_eth() -> FakeInfo:
    return FakeInfo(
        responses={
            "": {
                "universe": [
                    {"name": "BTC", "szDecimals": 5, "maxLeverage": 50},
                    {"name": "ETH", "szDecimals": 4, "maxLeverage": 50},
                ]
            },
            "xyz": {
                "universe": [
                    {"name": "TSLA", "szDecimals": 2, "maxLeverage": 50},
                    {"name": "SP500", "szDecimals": 2, "maxLeverage": 50},
                ]
            },
            "cash": {"universe": [{"name": "GOLD", "szDecimals": 2, "maxLeverage": 20}]},
        }
    )


class TestUniverseManagerRefresh:
    def test_first_refresh_inserts_all(self, db) -> None:
        um = UniverseManager(db, info=_info_with_btc_and_eth())
        result = um.refresh()
        assert result.markets_total == 5
        assert result.markets_added == 5
        assert result.markets_deactivated == 0

    def test_second_refresh_is_idempotent(self, db) -> None:
        info = _info_with_btc_and_eth()
        um = UniverseManager(db, info=info)
        um.refresh()
        result = um.refresh()
        assert result.markets_added == 0
        assert result.markets_deactivated == 0

    def test_missing_market_is_deactivated_not_dropped(self, db) -> None:
        info = _info_with_btc_and_eth()
        um = UniverseManager(db, info=info)
        um.refresh()

        # Drop BTC from the fake Info response.
        info.responses[""] = {
            "universe": [{"name": "ETH", "szDecimals": 4, "maxLeverage": 50}]
        }
        result = um.refresh()
        assert result.markets_deactivated == 1

        btc = um.get("perp:BTC")
        assert btc is not None
        assert btc["active"] is False

    def test_reactivation_on_return(self, db) -> None:
        info = _info_with_btc_and_eth()
        um = UniverseManager(db, info=info)
        um.refresh()
        # Drop BTC
        info.responses[""] = {"universe": [{"name": "ETH"}]}
        um.refresh()
        # BTC comes back
        info.responses[""] = {"universe": [{"name": "BTC"}, {"name": "ETH"}]}
        result = um.refresh()
        assert result.markets_reactivated == 1

    def test_hip3_symbols_are_prefixed(self, db) -> None:
        um = UniverseManager(db, info=_info_with_btc_and_eth())
        um.refresh()
        tsla = um.get("perp:xyz:TSLA")
        assert tsla is not None
        assert tsla["dex"] == "xyz"
        assert tsla["category"] == "stock"
        assert tsla["base"] == "TSLA"

    def test_native_perp_category_is_crypto(self, db) -> None:
        um = UniverseManager(db, info=_info_with_btc_and_eth())
        um.refresh()
        btc = um.get("perp:BTC")
        assert btc["category"] == "crypto"

    def test_outcome_markets_absorbed(self, db) -> None:
        um = UniverseManager(
            db,
            info=_info_with_btc_and_eth(),
            outcome_client=FakeOutcomeClient(
                markets=[
                    {"id": "0xabc", "symbol": "BTC_100K_EOY", "category": "crypto"},
                ]
            ),
        )
        um.refresh()
        outcomes = um.list_markets(kind="outcome")
        assert len(outcomes) == 1
        assert outcomes[0]["id"] == "outcome:0xabc"

    def test_info_errors_dont_kill_refresh(self, db) -> None:
        class BadInfo:
            def meta(self, dex=""):
                raise RuntimeError("rpc dead")

        um = UniverseManager(db, info=BadInfo())
        # Should complete without raising.
        result = um.refresh()
        assert result.markets_total == 0


class TestUniverseManagerTagging:
    def test_tag_untag_roundtrip(self, db) -> None:
        um = UniverseManager(db, info=_info_with_btc_and_eth())
        um.refresh()
        um.tag("perp:BTC", "trade")
        um.tag("perp:BTC", "watch")
        um.tag("perp:ETH", "watch")

        btc = um.get("perp:BTC")
        assert set(btc["tags"]) == {"trade", "watch"}

        watchlist = um.markets_by_tag("watch")
        assert {m["id"] for m in watchlist} == {"perp:BTC", "perp:ETH"}

        um.untag("perp:BTC", "trade")
        btc = um.get("perp:BTC")
        assert btc["tags"] == ["watch"]

    def test_duplicate_tag_insert_is_idempotent(self, db) -> None:
        um = UniverseManager(db, info=_info_with_btc_and_eth())
        um.refresh()
        um.tag("perp:BTC", "trade")
        um.tag("perp:BTC", "trade")  # second call no-op
        btc = um.get("perp:BTC")
        assert btc["tags"] == ["trade"]


class TestUniverseManagerListFilters:
    def test_filter_by_kind(self, db) -> None:
        um = UniverseManager(
            db,
            info=_info_with_btc_and_eth(),
            outcome_client=FakeOutcomeClient(markets=[{"id": "0xabc", "symbol": "x"}]),
        )
        um.refresh()
        perps = um.list_markets(kind="perp")
        outcomes = um.list_markets(kind="outcome")
        assert all(m["kind"] == "perp" for m in perps)
        assert all(m["kind"] == "outcome" for m in outcomes)

    def test_filter_by_category(self, db) -> None:
        um = UniverseManager(db, info=_info_with_btc_and_eth())
        um.refresh()
        stocks = um.list_markets(category="stock")
        assert {m["base"] for m in stocks} == {"TSLA"}

    def test_active_only_flag(self, db) -> None:
        info = _info_with_btc_and_eth()
        um = UniverseManager(db, info=info)
        um.refresh()
        info.responses[""] = {"universe": []}  # drop all native
        um.refresh()

        active = um.list_markets(kind="perp", active_only=True)
        total = um.list_markets(kind="perp", active_only=False)
        assert len(total) > len(active)
