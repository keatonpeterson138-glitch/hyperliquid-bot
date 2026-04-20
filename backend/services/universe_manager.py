"""UniverseManager — discovers Hyperliquid markets dynamically.

Refreshes the ``markets`` SQLite table from:
1. Native perps (Hyperliquid Info ``meta()``).
2. HIP-3 perps across all known deployer dexes (Info ``meta(dex=...)``).
3. HIP-4 outcome markets (``OutcomeClient.list_markets()``).

Anything missing on refresh is soft-deleted (``active=0``), not dropped,
so historical audit / trade rows remain linkable. New listings surface
as ``active=1`` rows with ``first_seen = now``.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from backend.db.app_db import AppDB

logger = logging.getLogger(__name__)


class MetaClient(Protocol):
    """Subset of ``hyperliquid.info.Info`` we depend on."""

    def meta(self, dex: str = "") -> dict[str, Any]: ...


class OutcomeMetaClient(Protocol):
    """Subset of ``core.outcome_client.OutcomeClient`` we depend on."""

    def list_markets(self) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class RefreshResult:
    markets_total: int
    markets_added: int
    markets_reactivated: int
    markets_deactivated: int


class UniverseManager:
    DEFAULT_HIP3_DEXES = ("cash", "xyz")

    def __init__(
        self,
        db: AppDB,
        *,
        info: MetaClient | None = None,
        outcome_client: OutcomeMetaClient | None = None,
        hip3_dexes: list[str] | tuple[str, ...] = DEFAULT_HIP3_DEXES,
    ) -> None:
        self.db = db
        self.info = info
        self.outcome_client = outcome_client
        self.hip3_dexes = list(hip3_dexes)

    # ── Refresh ────────────────────────────────────────────────────────────

    def refresh(self) -> RefreshResult:
        now = datetime.now(UTC)
        seen_ids: set[str] = set()
        added = 0
        reactivated = 0
        total = 0

        for market in self._discover():
            total += 1
            seen_ids.add(market["id"])
            did_add, did_reactivate = self._upsert(market, now)
            added += int(did_add)
            reactivated += int(did_reactivate)

        deactivated = self._deactivate_missing(seen_ids, now)
        return RefreshResult(
            markets_total=total,
            markets_added=added,
            markets_reactivated=reactivated,
            markets_deactivated=deactivated,
        )

    def _discover(self) -> list[dict[str, Any]]:
        """Fetch from all configured sources. Errors on one source don't kill the refresh."""
        markets: list[dict[str, Any]] = []

        if self.info is not None:
            try:
                native = self.info.meta()
                markets.extend(_normalize_perp_meta(native, dex=""))
            except Exception as exc:  # noqa: BLE001
                logger.error("Native perp meta fetch failed: %s", exc)

            for dex in self.hip3_dexes:
                try:
                    data = self.info.meta(dex=dex)
                    markets.extend(_normalize_perp_meta(data, dex=dex))
                except Exception as exc:  # noqa: BLE001
                    logger.error("HIP-3 meta fetch failed for dex=%s: %s", dex, exc)

        if self.outcome_client is not None:
            try:
                for raw in self.outcome_client.list_markets():
                    markets.append(_normalize_outcome_meta(raw))
            except Exception as exc:  # noqa: BLE001
                logger.error("HIP-4 outcome list failed: %s", exc)

        return markets

    def _upsert(self, market: dict[str, Any], now: datetime) -> tuple[bool, bool]:
        """Upsert a single market row. Returns (newly_added, reactivated)."""
        with self.db.transaction() as conn:
            existing = conn.execute(
                "SELECT active FROM markets WHERE id = ?", (market["id"],)
            ).fetchone()

            if existing is None:
                conn.execute(
                    """
                    INSERT INTO markets(
                        id, kind, symbol, dex, base, category, subcategory,
                        max_leverage, sz_decimals, tick_size, min_size,
                        resolution_date, bounds_json, active, first_seen, last_seen
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        market["id"],
                        market["kind"],
                        market["symbol"],
                        market.get("dex", ""),
                        market.get("base"),
                        market.get("category"),
                        market.get("subcategory"),
                        market.get("max_leverage"),
                        market.get("sz_decimals"),
                        market.get("tick_size"),
                        market.get("min_size"),
                        market.get("resolution_date"),
                        json.dumps(market["bounds"]) if market.get("bounds") else None,
                        now,
                        now,
                    ),
                )
                return True, False

            reactivated = bool(existing[0] == 0)
            conn.execute(
                """
                UPDATE markets SET
                    kind = ?, symbol = ?, dex = ?, base = ?, category = ?,
                    subcategory = ?, max_leverage = ?, sz_decimals = ?,
                    tick_size = ?, min_size = ?, resolution_date = ?,
                    bounds_json = ?, active = 1, last_seen = ?
                WHERE id = ?
                """,
                (
                    market["kind"],
                    market["symbol"],
                    market.get("dex", ""),
                    market.get("base"),
                    market.get("category"),
                    market.get("subcategory"),
                    market.get("max_leverage"),
                    market.get("sz_decimals"),
                    market.get("tick_size"),
                    market.get("min_size"),
                    market.get("resolution_date"),
                    json.dumps(market["bounds"]) if market.get("bounds") else None,
                    now,
                    market["id"],
                ),
            )
            return False, reactivated

    def _deactivate_missing(self, seen_ids: set[str], now: datetime) -> int:
        if not seen_ids:
            return 0
        placeholders = ",".join("?" for _ in seen_ids)
        with self.db.transaction() as conn:
            cursor = conn.execute(
                f"UPDATE markets SET active = 0, last_seen = ? "
                f"WHERE active = 1 AND id NOT IN ({placeholders})",
                (now, *seen_ids),
            )
            return cursor.rowcount or 0

    # ── Reads ──────────────────────────────────────────────────────────────

    def list_markets(
        self,
        *,
        kind: str | None = None,
        category: str | None = None,
        active_only: bool = True,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if active_only:
            clauses.append("active = 1")
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        if category is not None:
            clauses.append("category = ?")
            params.append(category)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self.db.fetchall(f"SELECT * FROM markets{where} ORDER BY symbol", tuple(params))
        return [_row_to_market(row, self._tags_for(row["id"])) for row in rows]

    def get(self, market_id: str) -> dict[str, Any] | None:
        row = self.db.fetchone("SELECT * FROM markets WHERE id = ?", (market_id,))
        if row is None:
            return None
        return _row_to_market(row, self._tags_for(market_id))

    def _tags_for(self, market_id: str) -> list[str]:
        rows = self.db.fetchall(
            "SELECT tag FROM market_tags WHERE market_id = ? ORDER BY tag", (market_id,)
        )
        return [row["tag"] for row in rows]

    def tag(self, market_id: str, tag: str) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO market_tags(market_id, tag) VALUES (?, ?)",
                (market_id, tag),
            )

    def untag(self, market_id: str, tag: str) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "DELETE FROM market_tags WHERE market_id = ? AND tag = ?",
                (market_id, tag),
            )

    def markets_by_tag(self, tag: str) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            """
            SELECT m.* FROM markets m
            JOIN market_tags t ON t.market_id = m.id
            WHERE t.tag = ? ORDER BY m.symbol
            """,
            (tag,),
        )
        return [_row_to_market(row, self._tags_for(row["id"])) for row in rows]


# ── Normalization ──────────────────────────────────────────────────────────


def _normalize_perp_meta(data: dict[str, Any], *, dex: str) -> list[dict[str, Any]]:
    """Hyperliquid ``meta()`` → list of canonical market dicts.

    The response layout is ``{"universe": [{name, szDecimals, maxLeverage, ...}]}``.
    """
    universe = data.get("universe") if isinstance(data, dict) else None
    if not isinstance(universe, list):
        return []
    out = []
    for idx, entry in enumerate(universe):
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not name:
            continue
        coin = name
        symbol = f"{dex}:{coin}" if dex else coin
        market_id = f"perp:{symbol}"
        out.append(
            {
                "id": market_id,
                "kind": "perp",
                "symbol": symbol,
                "dex": dex,
                "base": coin,
                "category": _infer_category(coin, dex),
                "subcategory": None,
                "max_leverage": _maybe_int(entry.get("maxLeverage")),
                "sz_decimals": _maybe_int(entry.get("szDecimals")),
                "tick_size": _maybe_float(entry.get("tickSize")),
                "min_size": _maybe_float(entry.get("minSize")),
                "_universe_index": idx,
            }
        )
    return out


def _normalize_outcome_meta(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a HIP-4 outcome-market payload to our canonical shape."""
    market_id = raw.get("id") or raw.get("market_id") or raw.get("coin")
    if market_id and not str(market_id).startswith("outcome:"):
        market_id = f"outcome:{market_id}"
    return {
        "id": str(market_id) if market_id else "",
        "kind": "outcome",
        "symbol": str(raw.get("symbol") or raw.get("name") or market_id or ""),
        "dex": "",
        "base": None,
        "category": "outcome",
        "subcategory": raw.get("subcategory") or raw.get("category"),
        "max_leverage": None,
        "sz_decimals": None,
        "tick_size": _maybe_float(raw.get("tick_size")),
        "min_size": _maybe_float(raw.get("min_size")),
        "resolution_date": raw.get("resolution_date"),
        "bounds": raw.get("bounds"),
    }


_STOCK_SYMBOLS = {
    "NVDA", "TSLA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "HOOD",
    "INTC", "PLTR", "COIN", "NFLX", "MSTR", "AMD", "TSM",
}
_INDEX_SYMBOLS = {"SP500", "XYZ100"}
_COMMODITY_SYMBOLS = {"GOLD", "SILVER", "OIL", "CORN", "WHEAT"}


def _infer_category(coin: str, dex: str) -> str:
    upper = coin.upper()
    if dex == "":
        return "crypto"
    if upper in _STOCK_SYMBOLS:
        return "stock"
    if upper in _INDEX_SYMBOLS:
        return "index"
    if upper in _COMMODITY_SYMBOLS:
        return "commodity"
    if dex == "cash":
        return "commodity"
    if dex == "xyz":
        return "stock"
    return "other"


def _maybe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _maybe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _row_to_market(row: Any, tags: list[str]) -> dict[str, Any]:
    """Row dict → canonical Market dict."""
    return {
        "id": row["id"],
        "kind": row["kind"],
        "symbol": row["symbol"],
        "dex": row["dex"],
        "base": row["base"],
        "category": row["category"],
        "subcategory": row["subcategory"],
        "max_leverage": row["max_leverage"],
        "sz_decimals": row["sz_decimals"],
        "tick_size": row["tick_size"],
        "min_size": row["min_size"],
        "resolution_date": row["resolution_date"],
        "bounds": json.loads(row["bounds_json"]) if row["bounds_json"] else None,
        "active": bool(row["active"]),
        "first_seen": row["first_seen"],
        "last_seen": row["last_seen"],
        "tags": tags,
    }
