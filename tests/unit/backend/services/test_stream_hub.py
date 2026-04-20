"""Tests for StreamHub."""
from __future__ import annotations

import asyncio

import pytest

from backend.services.stream_hub import StreamHub


@pytest.mark.asyncio
async def test_publish_delivers_to_subscriber() -> None:
    hub = StreamHub()
    q = await hub.subscribe()
    hub.publish({"type": "tick", "value": 42})
    event = await asyncio.wait_for(q.get(), timeout=1.0)
    assert event["type"] == "tick"
    assert event["value"] == 42
    assert "ts" in event


@pytest.mark.asyncio
async def test_multiple_subscribers_all_receive() -> None:
    hub = StreamHub()
    q1 = await hub.subscribe()
    q2 = await hub.subscribe()
    hub.publish({"type": "broadcast"})
    e1 = await asyncio.wait_for(q1.get(), timeout=1.0)
    e2 = await asyncio.wait_for(q2.get(), timeout=1.0)
    assert e1["type"] == "broadcast"
    assert e2["type"] == "broadcast"


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery() -> None:
    hub = StreamHub()
    q = await hub.subscribe()
    await hub.unsubscribe(q)
    hub.publish({"type": "after_unsub"})
    # Queue should remain empty.
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(q.get(), timeout=0.1)


def test_publish_without_subscribers_is_noop() -> None:
    hub = StreamHub()
    # Should not raise.
    hub.publish({"type": "nobody_listening"})
    assert hub.subscriber_count == 0
