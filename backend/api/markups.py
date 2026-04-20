"""/markups — chart drawings."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from backend.models.markup import MarkupCreate, MarkupOut, MarkupUpdate
from backend.services.markup_store import Markup, MarkupStore

router = APIRouter(tags=["markups"])


def get_markup_store() -> MarkupStore:
    raise HTTPException(status_code=503, detail="MarkupStore not configured")


StoreDep = Annotated[MarkupStore, Depends(get_markup_store)]


def _to_out(m: Markup) -> MarkupOut:
    return MarkupOut(
        id=m.id,
        layout_id=m.layout_id,
        symbol=m.symbol,
        interval=m.interval,
        tool_id=m.tool_id,
        payload=m.payload,
        style=m.style,
        z=m.z,
        locked=m.locked,
        hidden=m.hidden,
        state=m.state,
        order_id=m.order_id,
    )


@router.get("/markups", response_model=list[MarkupOut])
def list_markups(
    store: StoreDep,
    symbol: str | None = None,
    interval: str | None = None,
    layout_id: str | None = None,
) -> list[MarkupOut]:
    return [_to_out(m) for m in store.list(symbol=symbol, interval=interval, layout_id=layout_id)]


@router.post("/markups", response_model=MarkupOut)
def create_markup(req: MarkupCreate, store: StoreDep) -> MarkupOut:
    m = store.create(**req.model_dump())
    return _to_out(m)


@router.patch("/markups/{markup_id}", response_model=MarkupOut)
def update_markup(markup_id: str, req: MarkupUpdate, store: StoreDep) -> MarkupOut:
    m = store.update(markup_id, req.model_dump(exclude_unset=True))
    if m is None:
        raise HTTPException(status_code=404, detail=f"Markup {markup_id} not found")
    return _to_out(m)


@router.delete("/markups/{markup_id}", status_code=204)
def delete_markup(markup_id: str, store: StoreDep) -> None:
    store.delete(markup_id)
