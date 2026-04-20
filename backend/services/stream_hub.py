"""StreamHub — in-process pub/sub for the WS /stream endpoint.

Trade engine, kill-switch, audit, and data-updater services emit events
via ``hub.publish(event)``; the WS endpoint subscribes and fans out
ordered messages to every connected client.

Implementation: per-subscriber asyncio.Queue. Producers are
non-blocking — slow consumers are dropped via queue overflow rather
than backing up the whole bus.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

_SUBSCRIBER_QUEUE_SIZE = 256


class StreamHub:
    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[dict[str, Any]]] = []
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_SUBSCRIBER_QUEUE_SIZE)
        async with self._lock:
            self._subscribers.append(q)
        return q

    async def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        async with self._lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass

    def publish(self, event: dict[str, Any]) -> None:
        """Sync publish — safe to call from any thread.

        The event is dropped silently if any subscriber's queue is full
        (slow-consumer protection). Each subscriber gets a copy.
        """
        if "ts" not in event:
            event = {"ts": datetime.now(UTC).isoformat(), **event}
        for q in list(self._subscribers):
            try:
                q.put_nowait(dict(event))
            except asyncio.QueueFull:
                logger.warning(
                    "StreamHub subscriber queue full — dropping event %s", event.get("type")
                )

    async def stream(self) -> AsyncIterator[dict[str, Any]]:
        """Convenience for tests + the WS endpoint to consume forever."""
        q = await self.subscribe()
        try:
            while True:
                yield await q.get()
        finally:
            await self.unsubscribe(q)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
