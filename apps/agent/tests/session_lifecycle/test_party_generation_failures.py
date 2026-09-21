"""Failure ownership across overlapping party connection generations."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from participant_lifecycle import _setup_party_join
from session_data import SessionData


def _participant(identity):
    return SimpleNamespace(identity=identity)


def _recording_room():
    room = MagicMock()
    room.remote_participants = {}
    handlers = {}

    def register(event, callback):
        handlers[event] = callback

    room.on.side_effect = register
    return room, handlers


async def test_failed_stale_hydration_cannot_poison_the_reconnected_generation():
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    calls = 0
    queries = MagicMock()

    async def lookup(pid):
        nonlocal calls
        calls += 1
        if calls == 1:
            first_started.set()
            await release_first.wait()
            raise OSError("stale lookup failed")
        return {"player_id": pid}

    queries.get_player = AsyncMock(side_effect=lookup)
    resonance = MagicMock(
        read_player_resonance=AsyncMock(return_value={"current": 0, "flickering_bonus": 0, "state": "stable"})
    )
    concentration = MagicMock(read_player_concentration=AsyncMock(return_value={"spell_id": None}))
    room, handlers = _recording_room()
    lifecycle = _setup_party_join(
        room,
        SessionData(player_id="player_1", location_id="loc"),
        queries=queries,
        resonance_mod=resonance,
        concentration_mod=concentration,
    )

    handlers["participant_connected"](_participant("player_2"))
    await first_started.wait()
    first_join = lifecycle._pending_joins["player_2"]
    handlers["participant_disconnected"](_participant("player_2"))
    handlers["participant_connected"](_participant("player_2"))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    generation = lifecycle.current_generation("player_2")
    assert generation == 2
    assert await lifecycle.authorize("player_2") == generation

    release_first.set()
    await asyncio.gather(first_join, return_exceptions=True)
    await asyncio.sleep(0)

    assert await lifecycle.authorize("player_2") == generation
