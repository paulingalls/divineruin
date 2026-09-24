import json
import logging
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from livekit import rtc

import game_events
from event_bus import EventBus, GameEvent

EVENT_TYPE = "world_changed"
PAYLOAD = {"location_id": "guild_hall", "count": 2}


def room(connected: bool = True, send: AsyncMock | None = None) -> rtc.Room:
    return cast(
        rtc.Room,
        SimpleNamespace(
            isconnected=Mock(return_value=connected),
            local_participant=SimpleNamespace(publish_data=send or AsyncMock()),
        ),
    )


def assert_one_event(bus: EventBus) -> None:
    events = bus.drain()
    assert len(events) == 1
    assert isinstance(events[0], GameEvent)
    assert events[0].event_type == EVENT_TYPE
    assert events[0].payload == PAYLOAD
    assert bus.drain() == []


async def test_bus_receives_event_before_client_send_fails():
    bus = EventBus()
    error = RuntimeError("client transport failed")

    async def failing_send(*args, **kwargs):
        assert bus.qsize == 1
        raise error

    send = AsyncMock(side_effect=failing_send)
    with pytest.raises(RuntimeError) as caught:
        await game_events.publish_game_event(room(send=send), EVENT_TYPE, PAYLOAD, bus)

    assert caught.value is error
    send.assert_awaited_once()
    assert_one_event(bus)


async def test_disconnected_room_still_publishes_to_bus(monkeypatch, caplog):
    bus = EventBus()
    send = AsyncMock()

    async def disconnected(_room):
        raise RuntimeError("room did not connect")

    monkeypatch.setattr(game_events, "_wait_for_connection", disconnected)
    with caplog.at_level(logging.WARNING):
        await game_events.publish_game_event(room(connected=False, send=send), EVENT_TYPE, PAYLOAD, bus)

    send.assert_not_awaited()
    assert_one_event(bus)
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert warnings[0].getMessage() == f"Room disconnected, skipping {EVENT_TYPE} event"


async def test_connected_room_sends_one_payload_and_publishes_one_event():
    bus = EventBus()
    send = AsyncMock()
    connected_room = room(send=send)

    await game_events.publish_game_event(connected_room, EVENT_TYPE, PAYLOAD, bus)

    send.assert_awaited_once()
    call = send.await_args
    assert call is not None
    args, kwargs = call
    assert len(args) == 1
    assert json.loads(args[0].decode("utf-8")) == {"type": EVENT_TYPE, **PAYLOAD}
    assert kwargs == {"reliable": True, "topic": "game_events"}
    assert_one_event(bus)
