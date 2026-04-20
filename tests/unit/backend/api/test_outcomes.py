"""API tests for /outcomes listing + /outcomes/{market_id}/tape."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
from fastapi.testclient import TestClient

from backend.api import outcomes as outcomes_api
from backend.api import universe as universe_api
from backend.db.app_db import AppDB
from backend.db.duckdb_catalog import DuckDBCatalog
from backend.db.parquet_writer import append_outcomes
from backend.main import create_app
from backend.services.universe_manager import UniverseManager


class _FakeOutcomeClient:
    def __init__(self, markets: list[dict]) -> None:
        self._markets = markets

    def list_markets(self) -> list[dict]:
        return self._markets


def _seed(tmp_path):
    ts = [datetime(2025, 11, 1, tzinfo=UTC) + timedelta(minutes=i) for i in range(3)]
    bars = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(ts, utc=True),
            "price": [0.42, 0.44, 0.46],
            "volume": [1000.0, 500.0, 750.0],
            "implied_prob": [0.42, 0.44, 0.46],
            "best_bid": [0.41, 0.43, 0.45],
            "best_ask": [0.43, 0.45, 0.47],
            "event_id": ["btc_100k"] * 3,
            "source": ["hyperliquid-outcomes"] * 3,
            "ingested_at": pd.to_datetime([datetime(2026, 4, 20, tzinfo=UTC)] * 3, utc=True),
        }
    )
    append_outcomes("market_abc", bars, data_root=tmp_path)


def _client(tmp_path) -> TestClient:
    app = create_app()
    app.dependency_overrides[outcomes_api.get_catalog] = lambda: DuckDBCatalog(tmp_path)
    return TestClient(app)


def test_returns_ticks_in_range(tmp_path) -> None:
    _seed(tmp_path)
    client = _client(tmp_path)
    resp = client.get(
        "/outcomes/market_abc/tape",
        params={"from": "2025-11-01T00:00:00Z", "to": "2025-12-01T00:00:00Z"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["market_id"] == "market_abc"
    assert body["tick_count"] == 3
    assert [t["price"] for t in body["ticks"]] == [0.42, 0.44, 0.46]


def test_empty_for_unknown_market(tmp_path) -> None:
    _seed(tmp_path)
    client = _client(tmp_path)
    resp = client.get(
        "/outcomes/does_not_exist/tape",
        params={"from": "2025-11-01T00:00:00Z"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["tick_count"] == 0
    assert body["ticks"] == []


def test_to_defaults_to_now(tmp_path) -> None:
    _seed(tmp_path)
    client = _client(tmp_path)
    resp = client.get(
        "/outcomes/market_abc/tape",
        params={"from": "2025-11-01T00:00:00Z"},
    )
    assert resp.status_code == 200
    assert resp.json()["tick_count"] == 3


# ── /outcomes listing ──────────────────────────────────────────────────────


def _universe_client(markets: list[dict]) -> tuple[TestClient, UniverseManager]:
    db = AppDB(":memory:")
    um = UniverseManager(db, outcome_client=_FakeOutcomeClient(markets))
    um.refresh()
    app = create_app()
    app.dependency_overrides[universe_api.get_universe_manager] = lambda: um
    return TestClient(app), um


_CANON_MARKETS = [
    {"id": "politics_x", "symbol": "Will X win?", "subcategory": "politics"},
    {"id": "sports_y", "symbol": "Will Y win?", "subcategory": "sports"},
    {"id": "crypto_btc100k", "symbol": "BTC 100k by EOY?", "subcategory": "crypto"},
]


def test_list_outcomes_returns_all_active() -> None:
    client, _ = _universe_client(_CANON_MARKETS)
    resp = client.get("/outcomes")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["markets"]) == 3
    assert {m["kind"] for m in body["markets"]} == {"outcome"}
    assert {m["id"] for m in body["markets"]} == {
        "outcome:politics_x",
        "outcome:sports_y",
        "outcome:crypto_btc100k",
    }


def test_list_outcomes_subcategory_filter() -> None:
    client, _ = _universe_client(_CANON_MARKETS)
    resp = client.get("/outcomes", params={"subcategory": "politics"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["markets"]) == 1
    assert body["markets"][0]["subcategory"] == "politics"


def test_list_outcomes_unknown_subcategory_empty() -> None:
    client, _ = _universe_client(_CANON_MARKETS)
    resp = client.get("/outcomes", params={"subcategory": "macro"})
    assert resp.status_code == 200
    assert resp.json()["markets"] == []


def test_list_outcomes_excludes_perps() -> None:
    """/outcomes must not leak perp markets from the same universe."""
    db = AppDB(":memory:")

    class _FakePerpInfo:
        def meta(self, dex: str = ""):
            if dex == "":
                return {"universe": [{"name": "BTC"}, {"name": "ETH"}]}
            return {"universe": []}

    um = UniverseManager(
        db,
        info=_FakePerpInfo(),
        outcome_client=_FakeOutcomeClient(_CANON_MARKETS),
        hip3_dexes=(),
    )
    um.refresh()
    app = create_app()
    app.dependency_overrides[universe_api.get_universe_manager] = lambda: um
    client = TestClient(app)

    resp = client.get("/outcomes")
    assert resp.status_code == 200
    assert len(resp.json()["markets"]) == 3  # 3 outcomes, not 5


def test_list_outcomes_503_when_um_not_wired() -> None:
    app = create_app()
    client = TestClient(app)
    resp = client.get("/outcomes")
    assert resp.status_code == 503


# ── /outcomes/{id}/edge ────────────────────────────────────────────────────


class _FakeBinaryPrice:
    def __init__(self, fair_yes: float, fair_no: float) -> None:
        self.fair_yes = fair_yes
        self.fair_no = fair_no


class _FakeAnalysis:
    def __init__(self, outcome_id: int, edge_yes: float | None) -> None:
        self.outcome_id = outcome_id
        self.underlying = "BTC"
        self.target_price = 100_000.0
        self.t_years = 0.25
        self.spot = 68_000.0
        self.vol_used = 0.8
        self.vol_source = "historical"
        self.theory = _FakeBinaryPrice(fair_yes=0.30, fair_no=0.70)
        self.market_yes = 0.25
        self.market_no = 0.75
        self.edge_yes = edge_yes
        self.edge_no = None if edge_yes is None else -edge_yes
        self.implied_vol = 0.72


class _FakePricingModel:
    def __init__(self, outcomes: dict[int, _FakeAnalysis | None]) -> None:
        self._outcomes = outcomes

    def analyse(
        self,
        outcome_id: int,
        vol: float | None = None,
        spot: float | None = None,
        default_vol: float = 0.80,
    ) -> _FakeAnalysis | None:
        return self._outcomes.get(outcome_id)


def _edge_client(outcomes: dict[int, _FakeAnalysis | None]) -> TestClient:
    app = create_app()
    app.dependency_overrides[outcomes_api.get_pricing_model] = lambda: _FakePricingModel(
        outcomes
    )
    return TestClient(app)


def test_edge_returns_theory_and_market() -> None:
    client = _edge_client({4557: _FakeAnalysis(4557, edge_yes=0.05)})
    resp = client.get("/outcomes/outcome:4557/edge")
    assert resp.status_code == 200
    body = resp.json()
    assert body["market_id"] == "outcome:4557"
    assert body["underlying"] == "BTC"
    assert body["theoretical_prob_yes"] == 0.30
    assert body["market_yes"] == 0.25
    assert body["edge_yes"] == 0.05
    assert body["vol_source"] == "historical"


def test_edge_accepts_bare_numeric_id() -> None:
    client = _edge_client({4557: _FakeAnalysis(4557, edge_yes=0.05)})
    resp = client.get("/outcomes/4557/edge")
    assert resp.status_code == 200
    assert resp.json()["market_id"] == "4557"


def test_edge_404_for_unknown_outcome() -> None:
    client = _edge_client({4557: None})
    resp = client.get("/outcomes/outcome:4557/edge")
    assert resp.status_code == 404


def test_edge_400_for_non_numeric_id() -> None:
    client = _edge_client({})
    resp = client.get("/outcomes/outcome:not_a_number/edge")
    assert resp.status_code == 400


def test_edge_503_when_pricing_not_wired() -> None:
    app = create_app()
    client = TestClient(app)
    resp = client.get("/outcomes/outcome:4557/edge")
    assert resp.status_code == 503
