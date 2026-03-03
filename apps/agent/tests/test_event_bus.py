"""Tests for the in-process event bus."""

import asyncio

import pytest

from event_bus import EventBus, GameEvent


class TestEventBus:
    async def test_publish_and_get(self):
        bus = EventBus()
        event = GameEvent(event_type="location_changed", payload={"location": "tavern"})
        bus.publish(event)
        got = await bus.get(timeout=1.0)
        assert got is not None
        assert got.event_type == "location_changed"
        assert got.payload == {"location": "tavern"}

    async def test_get_timeout_returns_none(self):
        bus = EventBus()
        got = await bus.get(timeout=0.05)
        assert got is None

    async def test_drain_returns_all_queued(self):
        bus = EventBus()
        for i in range(5):
            bus.publish(GameEvent(event_type=f"event_{i}", payload={"i": i}))
        assert bus.qsize == 5
        events = bus.drain()
        assert len(events) == 5
        assert bus.qsize == 0
        assert [e.event_type for e in events] == [f"event_{i}" for i in range(5)]

    async def test_drain_empty_returns_empty_list(self):
        bus = EventBus()
        assert bus.drain() == []

    async def test_overflow_drops_oldest(self):
        bus = EventBus(maxsize=3)
        bus.publish(GameEvent(event_type="first", payload={}))
        bus.publish(GameEvent(event_type="second", payload={}))
        bus.publish(GameEvent(event_type="third", payload={}))
        # Queue is full — next publish drops oldest
        bus.publish(GameEvent(event_type="fourth", payload={}))
        assert bus.qsize == 3
        events = bus.drain()
        assert [e.event_type for e in events] == ["second", "third", "fourth"]

    async def test_timestamp_auto_set(self):
        event = GameEvent(event_type="test", payload={})
        assert event.timestamp > 0
