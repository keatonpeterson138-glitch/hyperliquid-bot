"""/slots — CRUD + start/stop for trading slots."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from backend.models.slot import SlotCreate, SlotOut, SlotUpdate
from backend.services.slot_repository import SlotRepository
from backend.services.trade_engine_service import TradeEngineService

router = APIRouter(tags=["slots"])


def get_slot_repo() -> SlotRepository:
    raise HTTPException(status_code=503, detail="SlotRepository not configured")


def get_trade_engine() -> TradeEngineService:
    raise HTTPException(status_code=503, detail="TradeEngineService not configured")


SlotRepoDep = Annotated[SlotRepository, Depends(get_slot_repo)]
TradeEngineDep = Annotated[TradeEngineService, Depends(get_trade_engine)]


def _to_out(slot, repo: SlotRepository) -> SlotOut:
    state = repo.get_state(slot.id)
    state_dict: dict[str, Any] | None = None
    if state is not None:
        state_dict = {
            "last_tick_at": state.last_tick_at,
            "last_signal": state.last_signal,
            "last_decision_action": state.last_decision_action,
            "current_position": state.current_position,
            "entry_price": state.entry_price,
            "position_size_usd": state.position_size_usd,
            "open_order_ids": state.open_order_ids,
        }
    return SlotOut(
        id=slot.id,
        kind=slot.kind,
        symbol=slot.symbol,
        strategy=slot.strategy,
        size_usd=slot.size_usd,
        interval=slot.interval,
        strategy_params=slot.strategy_params,
        leverage=slot.leverage,
        stop_loss_pct=slot.stop_loss_pct,
        take_profit_pct=slot.take_profit_pct,
        enabled=slot.enabled,
        shadow_enabled=slot.shadow_enabled,
        trailing_sl=slot.trailing_sl,
        mtf_enabled=slot.mtf_enabled,
        regime_filter=slot.regime_filter,
        atr_stops=slot.atr_stops,
        loss_cooldown=slot.loss_cooldown,
        volume_confirm=slot.volume_confirm,
        rsi_guard=slot.rsi_guard,
        rsi_guard_low=slot.rsi_guard_low,
        rsi_guard_high=slot.rsi_guard_high,
        ml_model_id=slot.ml_model_id,
        state=state_dict,
    )


@router.get("/slots", response_model=list[SlotOut])
def list_slots(repo: SlotRepoDep, enabled_only: bool = False) -> list[SlotOut]:
    return [_to_out(s, repo) for s in repo.list_all(enabled_only=enabled_only)]


@router.post("/slots", response_model=SlotOut)
def create_slot(req: SlotCreate, repo: SlotRepoDep) -> SlotOut:
    from backend.models.slot import Slot

    slot = repo.create(Slot(id="", **req.model_dump()))
    return _to_out(slot, repo)


@router.get("/slots/{slot_id}", response_model=SlotOut)
def get_slot(slot_id: str, repo: SlotRepoDep) -> SlotOut:
    slot = repo.get(slot_id)
    if slot is None:
        raise HTTPException(status_code=404, detail=f"Slot {slot_id} not found")
    return _to_out(slot, repo)


@router.patch("/slots/{slot_id}", response_model=SlotOut)
def update_slot(slot_id: str, req: SlotUpdate, repo: SlotRepoDep) -> SlotOut:
    fields = req.model_dump(exclude_unset=True)
    slot = repo.update(slot_id, fields)
    if slot is None:
        raise HTTPException(status_code=404, detail=f"Slot {slot_id} not found")
    return _to_out(slot, repo)


@router.delete("/slots/{slot_id}", status_code=204)
def delete_slot(slot_id: str, repo: SlotRepoDep) -> None:
    repo.delete(slot_id)


@router.post("/slots/{slot_id}/start", response_model=SlotOut)
def start_slot(slot_id: str, engine: TradeEngineDep, repo: SlotRepoDep) -> SlotOut:
    slot = engine.start_slot(slot_id)
    if slot is None:
        raise HTTPException(status_code=404, detail=f"Slot {slot_id} not found")
    return _to_out(slot, repo)


@router.post("/slots/{slot_id}/stop", response_model=SlotOut)
def stop_slot(slot_id: str, engine: TradeEngineDep, repo: SlotRepoDep) -> SlotOut:
    slot = engine.stop_slot(slot_id)
    if slot is None:
        raise HTTPException(status_code=404, detail=f"Slot {slot_id} not found")
    return _to_out(slot, repo)


@router.post("/slots/stop-all")
def stop_all(engine: TradeEngineDep) -> dict[str, int]:
    n = engine.stop_all()
    return {"slots_stopped": n}


@router.post("/slots/{slot_id}/tick")
def tick_slot(slot_id: str, engine: TradeEngineDep) -> dict[str, Any]:
    """Manually trigger one decision tick — useful for dev/test/UI 'run-now'."""
    decision = engine.tick(slot_id)
    return {
        "slot_id": slot_id,
        "action": decision.action.value,
        "reason": decision.reason,
        "strength": decision.strength,
        "rejection": decision.rejection,
    }
