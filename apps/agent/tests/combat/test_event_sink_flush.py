import asyncio
import json
from unittest.mock import call, create_autospec

import pytest
from livekit import rtc

from combat_events import EventSink
from event_bus import EventBus

EVENTS = [("first", {"value": 1}), ("second", {"value": 2}), ("third", {"value": 3})]


async def buffered_sink(monkeypatch, failures):
    room = rtc.Room()
    participant = create_autospec(rtc.LocalParticipant, instance=True)
    participant.publish_data.side_effect = failures
    monkeypatch.setattr(rtc.Room, "isconnected", lambda self: True)
    monkeypatch.setattr(rtc.Room, "local_participant", property(lambda self: participant))
    bus = EventBus()
    sink = EventSink()
    for event_type, payload in EVENTS:
        await sink.emit(room, event_type, payload, event_bus=bus)
    return sink, bus, participant.publish_data


def assert_delivery(bus, send, count=3):
    assert [(event.event_type, event.payload) for event in bus.drain()] == EVENTS[:count]
    assert send.await_args_list == [
        call(json.dumps({"type": event_type, **payload}).encode("utf-8"), reliable=True, topic="game_events")
        for event_type, payload in EVENTS[:count]
    ]


async def assert_inert_reflush(sink, bus, send):
    assert sink.captured == []
    calls = list(send.await_args_list)
    await sink.flush()
    assert bus.drain() == []
    assert send.await_args_list == calls


async def test_first_send_failure_still_delivers_the_whole_batch(monkeypatch):
    error = RuntimeError("first send failed")
    sink, bus, send = await buffered_sink(monkeypatch, [error, None, None])
    with pytest.raises(RuntimeError) as caught:
        await sink.flush()
    assert caught.value is error
    assert_delivery(bus, send)
    await assert_inert_reflush(sink, bus, send)


async def test_all_send_failures_raise_the_first_error_after_delivering_the_batch(monkeypatch):
    errors = [RuntimeError(f"send {i} failed") for i in range(3)]
    sink, bus, send = await buffered_sink(monkeypatch, errors)
    with pytest.raises(RuntimeError) as caught:
        await sink.flush()
    assert caught.value is errors[0]
    assert_delivery(bus, send)
    await assert_inert_reflush(sink, bus, send)


async def test_healthy_flush_publishes_and_sends_each_event_once_in_order(monkeypatch):
    sink, bus, send = await buffered_sink(monkeypatch, [None, None, None])
    await sink.flush()
    assert_delivery(bus, send)
    await assert_inert_reflush(sink, bus, send)


async def test_cancelled_flush_aborts_and_clears_without_replay(monkeypatch):
    cancellation = asyncio.CancelledError("cancelled")
    sink, bus, send = await buffered_sink(monkeypatch, [RuntimeError("first failed"), cancellation, None])
    with pytest.raises(asyncio.CancelledError) as caught:
        await sink.flush()
    assert caught.value is cancellation
    assert_delivery(bus, send, count=2)
    await assert_inert_reflush(sink, bus, send)
