"""/stream — WebSocket fan-out of trading + system events.

Subscribers get every event published to the StreamHub. Wire up the hub
in ``backend/main.py`` and pass ``publish=hub.publish`` into TradeEngine,
KillSwitch, and AuditService callbacks.
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
