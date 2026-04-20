"""/stream — WebSocket fan-out of trading + system events.

Subscribers get every event published to the StreamHub.

``/stream``                 — global bus (all events).
``/stream/outcomes?market_id=…`` — filtered channel: only ``outcome_edge``
  / ``decision`` / ``fill`` events whose ``market_id`` (or ``slot_id`` for
  outcome slots) matches the query.
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from backend.services.stream_hub import StreamHub

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stream"])


def get_stream_hub() -> StreamHub:
    raise NotImplementedError("StreamHub not configured")


HubDep = Annotated[StreamHub, Depends(get_stream_hub)]


@router.websocket("/stream")
async def stream(ws: WebSocket, hub: HubDep) -> None:
    await ws.accept()
    queue = await hub.subscribe()
    try:
        while True:
            event = await queue.get()
            await ws.send_json(event)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.exception("WS /stream error: %s", exc)
    finally:
        await hub.unsubscribe(queue)


@router.websocket("/stream/outcomes")
async def stream_outcomes(ws: WebSocket, hub: HubDep, market_id: str | None = None) -> None:
    """Filtered fan-out for a single outcome market. If ``market_id`` is
    omitted, all outcome-namespaced events are forwarded."""
    await ws.accept()
    queue = await hub.subscribe()
    try:
        while True:
            event = await queue.get()
            if not _is_outcome_event(event):
                continue
            if market_id is not None and event.get("market_id") != market_id:
                continue
            await ws.send_json(event)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.exception("WS /stream/outcomes error: %s", exc)
    finally:
        await hub.unsubscribe(queue)


_OUTCOME_EVENT_TYPES = frozenset({
    "outcome_edge", "outcome_fill", "outcome_decision", "outcome_tick",
})


def _is_outcome_event(event: dict) -> bool:
    et = event.get("type", "")
    if et in _OUTCOME_EVENT_TYPES:
        return True
    # Also pass through generic events that carry a market_id.
    return isinstance(event.get("market_id"), str)
