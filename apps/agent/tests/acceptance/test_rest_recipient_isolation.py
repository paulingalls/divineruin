"""Rest snapshots reach only their owning LiveKit participants."""

import asyncio
import json
from typing import cast
from unittest.mock import MagicMock
from uuid import uuid4

from acceptance._livekit_client import (
    aclose_room,
    connect_room,
    mint_access_token,
    register_data_packet_collector,
    wait_for_peer,
)
from acceptance.rest_walk import RestWalk

import event_types as E
from event_bus import EventBus


def test_rest_snapshots_are_private_to_each_owner(harness, livekit_server):
    async def check():
        walk = await RestWalk().setup(harness)
        walk.sd.event_bus = EventBus()
        room_name = "rest-privacy-" + uuid4().hex
        rooms, queues, unregisters = [], [], []
        try:
            for identity in ("dm", *walk.ids[:2]):
                token = mint_access_token(
                    api_key=livekit_server["api_key"],
                    api_secret=livekit_server["api_secret"],
                    room_name=room_name,
                    identity=identity,
                )
                rooms.append(await connect_room(livekit_server["ws_url"], token))
            sender = rooms[0]
            for receiver, pid in zip(rooms[1:], walk.ids[:2], strict=True):
                await wait_for_peer(sender, identity=pid)
                await wait_for_peer(receiver, identity="dm")
                queue = asyncio.Queue()
                queues.append(queue)
                unregisters.append(register_data_packet_collector(receiver, topic="game_events", queue=queue))

            async def relay(raw, **kwargs):
                await sender.local_participant.publish_data(raw, **kwargs)
                await walk.publish(raw, **kwargs)

            cast(MagicMock, walk.sd.room).local_participant.publish_data.side_effect = relay
            receipt = await walk.command("long")
            assert not receipt.is_error, receipt.output
            snapshots = [e for e in walk.sd.event_bus.drain() if e.event_type == E.SESSION_INIT]
            assert sorted(e.payload["character"]["player_id"] for e in snapshots) == sorted(
                [walk.ids[i] for i in (0, 1, 4)]
            )
            await sender.local_participant.publish_data(b'{"type":"drained"}', reliable=True, topic="game_events")
            for pid, queue in zip(walk.ids[:2], queues, strict=True):
                received = []
                async with asyncio.timeout(5):
                    while True:
                        raw, identity = await queue.get()
                        assert identity == "dm"
                        event = json.loads(raw)
                        if event["type"] == "drained":
                            break
                        received.append(event)
                snapshots = [event for event in received if event["type"] == E.SESSION_INIT]
                assert [event["character"]["player_id"] for event in snapshots] == [pid]
                assert snapshots[0]["character"]["hp"] == (await walk.row(pid))["hp"]
                assert all(key in snapshots[0] for key in ("inventory", "quests", "spells", "map_progress"))
        finally:
            for unregister in unregisters:
                unregister()
            for room in rooms:
                await aclose_room(room)

    harness.run_sync(check())
