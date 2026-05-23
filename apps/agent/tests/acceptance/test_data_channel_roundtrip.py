"""Acceptance: LiveKit data-channel round-trip via two participants.

Production publishes via `publish_game_event` -> `room.local_participant.publish_data`
on topic "game_events" with a FLAT wire format: json.dumps({"type": event_type, **payload}).
The unit-test layer mocks `publish_data`; this test is the only place that exercises
the actual SFU path with a real second participant receiving the bytes.

Two participants are required: LiveKit data-channel packets are NOT delivered back
to the publishing participant, so a single-room test would silently no-op.

Gated by the `livekit_server` fixture's REQUIRE_DOCKER pattern — skips cleanly when
Docker is unavailable and hard-fails when REQUIRE_DOCKER=1.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from acceptance._livekit_client import (
    register_data_packet_collector,
    wait_for_peer,
)

import event_types as E
from game_events import publish_game_event


def test_livekit_server_reachable(livekit_server: dict[str, str]) -> None:
    """Smoke check: LiveKit dev server starts and answers HTTP on the WS port."""
    response = httpx.get(livekit_server["http_url"], timeout=5.0)
    # Any 2xx-4xx response proves the server is up and routing requests.
    assert 200 <= response.status_code < 500


@pytest.mark.asyncio
async def test_session_init_event_round_trips(
    async_room_pair: tuple,
) -> None:
    """A SESSION_INIT event published by one participant reaches the other byte-exact."""
    publisher, subscriber, _room_name = async_room_pair

    queue: asyncio.Queue = asyncio.Queue()
    # The unregister callable is intentionally discarded — the async_room_pair
    # fixture's aclose_room(subscriber) on teardown detaches the listener with
    # the room disconnect. If a future test adds a second collector against the
    # same subscriber, bind the returned callable via pytest's addfinalizer to
    # avoid leaking listeners across the (then-shared) subscriber lifetime.
    register_data_packet_collector(subscriber, topic="game_events", queue=queue)

    # Both sides must see each other before publishing. Publisher-only wait is
    # insufficient: even after participant_connected fires on publisher, the
    # subscriber's data-channel subscription may still be negotiating, and the
    # SFU can queue or drop the packet against a half-set-up peer. Symmetric
    # wait ensures the subscriber's data_received pipe is wired.
    await asyncio.gather(
        wait_for_peer(publisher, identity="acceptance-subscriber", timeout=5.0),
        wait_for_peer(subscriber, identity="acceptance-publisher", timeout=5.0),
    )

    payload = {"session_id": "test-sess", "character_name": "Acceptance"}
    await publish_game_event(
        publisher,
        event_type=E.SESSION_INIT,
        payload=payload,
        event_bus=None,
    )

    bytes_, identity = await asyncio.wait_for(queue.get(), timeout=5.0)
    # FLAT wire format — publish_game_event spreads payload at top level
    # (game_events.py:55): json.dumps({"type": event_type, **payload}).
    decoded = json.loads(bytes_.decode("utf-8"))
    assert decoded == {"type": E.SESSION_INIT, **payload}
    assert identity == "acceptance-publisher"
