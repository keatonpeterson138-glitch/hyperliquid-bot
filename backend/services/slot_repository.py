"""SlotRepository — thin DB wrapper for the ``slots`` + ``slot_state`` tables."""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from backend.db.app_db import AppDB
from backend.models.slot import Slot, SlotState


def _row_to_slot(row: Any) -> Slot:
    return Slot(
        id=row["id"],
        kind=row["kind"],
        symbol=row["symbol"],
        strategy=row["strategy"],
        size_usd=row["size_usd"],
        interval=row["interval"],
        strategy_params=json.loads(row["strategy_params_json"] or "{}"),
        leverage=row["leverage"],
        stop_loss_pct=row["stop_loss_pct"],
        take_profit_pct=row["take_profit_pct"],
        enabled=bool(row["enabled"]),
        shadow_enabled=bool(row["shadow_enabled"]),
        trailing_sl=bool(row["trailing_sl"]),
        mtf_enabled=bool(row["mtf_enabled"]),
        regime_filter=bool(row["regime_filter"]),
        atr_stops=bool(row["atr_stops"]),
        loss_cooldown=bool(row["loss_cooldown"]),
        volume_confirm=bool(row["volume_confirm"]),
        rsi_guard=bool(row["rsi_guard"]),
        rsi_guard_low=row["rsi_guard_low"],
        rsi_guard_high=row["rsi_guard_high"],
        ml_model_id=row["ml_model_id"],
    )


def _row_to_state(row: Any) -> SlotState:
    return SlotState(
        slot_id=row["slot_id"],
        last_tick_at=row["last_tick_at"],
        last_signal=row["last_signal"],
        last_decision_action=row["last_decision_action"],
        current_position=row["current_position"],
        entry_price=row["entry_price"],
        position_size_usd=row["position_size_usd"],
        open_order_ids=json.loads(row["open_order_ids_json"] or "[]"),
    )


class SlotRepository:
    def __init__(self, db: AppDB) -> None:
        self.db = db

    # ── Slots CRUD ─────────────────────────────────────────────────────────

    def create(self, slot: Slot | dict[str, Any]) -> Slot:
        if isinstance(slot, dict):
            slot = Slot(id=slot.get("id") or _new_id(), **{k: v for k, v in slot.items() if k != "id"})
        elif not slot.id:
            slot = Slot(**{**asdict(slot), "id": _new_id()})

        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO slots(
                    id, kind, symbol, interval, strategy, strategy_params_json,
                    size_usd, leverage, stop_loss_pct, take_profit_pct,
                    enabled, shadow_enabled, trailing_sl, mtf_enabled,
                    regime_filter, atr_stops, loss_cooldown, volume_confirm,
                    rsi_guard, rsi_guard_low, rsi_guard_high, ml_model_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    slot.id, slot.kind, slot.symbol, slot.interval, slot.strategy,
                    json.dumps(slot.strategy_params), slot.size_usd, slot.leverage,
                    slot.stop_loss_pct, slot.take_profit_pct,
                    int(slot.enabled), int(slot.shadow_enabled),
                    int(slot.trailing_sl), int(slot.mtf_enabled),
                    int(slot.regime_filter), int(slot.atr_stops),
                    int(slot.loss_cooldown), int(slot.volume_confirm),
                    int(slot.rsi_guard), slot.rsi_guard_low, slot.rsi_guard_high,
                    slot.ml_model_id,
                ),
            )
        return slot

    def get(self, slot_id: str) -> Slot | None:
        row = self.db.fetchone("SELECT * FROM slots WHERE id = ?", (slot_id,))
        return _row_to_slot(row) if row else None

    def list_all(self, *, enabled_only: bool = False) -> list[Slot]:
        sql = "SELECT * FROM slots"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY created_at DESC"
        return [_row_to_slot(r) for r in self.db.fetchall(sql)]

    def update(self, slot_id: str, fields: dict[str, Any]) -> Slot | None:
        if not fields:
            return self.get(slot_id)

        # Translate UI-friendly field names to DB column names.
        translation = {"strategy_params": "strategy_params_json"}
        col_values: dict[str, Any] = {}
        for k, v in fields.items():
            col = translation.get(k, k)
            if k == "strategy_params":
                v = json.dumps(v or {})
            elif isinstance(v, bool):
                v = int(v)
            col_values[col] = v
        col_values["updated_at"] = datetime.now(UTC)

        cols = ", ".join(f"{k} = ?" for k in col_values)
        params: list[Any] = list(col_values.values())
        params.append(slot_id)

        with self.db.transaction() as conn:
            conn.execute(f"UPDATE slots SET {cols} WHERE id = ?", params)
        return self.get(slot_id)

    def delete(self, slot_id: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM slots WHERE id = ?", (slot_id,))

    # ── State ──────────────────────────────────────────────────────────────

    def get_state(self, slot_id: str) -> SlotState | None:
        row = self.db.fetchone("SELECT * FROM slot_state WHERE slot_id = ?", (slot_id,))
        return _row_to_state(row) if row else None

    def upsert_state(
        self,
        slot_id: str,
        *,
        last_tick_at: datetime | None = None,
        last_signal: str | None = None,
        last_decision_action: str | None = None,
        current_position: str | None = None,
        entry_price: float | None = None,
        position_size_usd: float | None = None,
        open_order_ids: list[str] | None = None,
    ) -> None:
        existing = self.get_state(slot_id)
        merged_orders = open_order_ids if open_order_ids is not None else (
            existing.open_order_ids if existing else []
        )
        merged = SlotState(
            slot_id=slot_id,
            last_tick_at=last_tick_at or (existing.last_tick_at if existing else None),
            last_signal=last_signal or (existing.last_signal if existing else None),
            last_decision_action=last_decision_action or (
                existing.last_decision_action if existing else None
            ),
            current_position=current_position if current_position is not None else (
                existing.current_position if existing else None
            ),
            entry_price=entry_price if entry_price is not None else (
                existing.entry_price if existing else None
            ),
            position_size_usd=position_size_usd if position_size_usd is not None else (
                existing.position_size_usd if existing else None
            ),
            open_order_ids=merged_orders,
        )
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO slot_state(
                    slot_id, last_tick_at, last_signal, last_decision_action,
                    current_position, entry_price, position_size_usd, open_order_ids_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(slot_id) DO UPDATE SET
                    last_tick_at = excluded.last_tick_at,
                    last_signal = excluded.last_signal,
                    last_decision_action = excluded.last_decision_action,
                    current_position = excluded.current_position,
                    entry_price = excluded.entry_price,
                    position_size_usd = excluded.position_size_usd,
                    open_order_ids_json = excluded.open_order_ids_json
                """,
                (
                    merged.slot_id, merged.last_tick_at, merged.last_signal,
                    merged.last_decision_action, merged.current_position,
                    merged.entry_price, merged.position_size_usd,
                    json.dumps(merged.open_order_ids),
                ),
            )


def _new_id() -> str:
    return f"slot_{uuid.uuid4().hex[:12]}"
