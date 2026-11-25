"""Still arrival and dwell saves across the lifetime of an encounter rally."""

import json
from unittest.mock import patch

from _zhael_marshal_rally_fixtures import CLAUSE, pending
from acceptance.test_still_absorption import HOUR, advance, background, charm
from acceptance.test_still_absorption import clock as clock
from acceptance.test_still_absorption import save_faces as save_faces
from acceptance.test_still_anchors import enter
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_still_paradise_trap import arrive, exploration, player_row
from acceptance.test_still_paradise_trap import paradise as paradise

import db_mutations
from movement_tools import party_level_warning


async def test_hourly_save_resets_on_success_and_reentry(paradise, clock, save_faces):
    walk, origin, zone = paradise
    guest = walk.players[1]
    await arrive(walk, "move_player", zone)
    await exploration(walk)
    _, state = await enter(walk)
    pending(state, guest, walk.players[0])
    await walk.persist()
    face, rolls = save_faces
    face.value = 17
    async with background(walk) as tick:
        await advance(clock, tick, HOUR)
        assert rolls == []
        assert (await walk.reload()).encounter_facts["rally_pending"] == {walk.players[0]: guest}
        await walk.command("end_combat", {"outcome": "fled"})
        assert await db_mutations.load_combat_state(state.combat_id) is None
        player = await player_row(walk.players[0])
        assert CLAUSE not in json.dumps(player.get("flags", {}))
        await tick()
        await advance(clock, tick, HOUR - 1)
        assert not rolls and await charm(guest, zone)
        await advance(clock, tick, 1)
        await tick()
        assert rolls == [(18, 0, 17)]
        assert await charm(guest, zone)
        await advance(clock, tick, HOUR)
        assert rolls == [(18, 0, 17), (18, 1, 18)]
        assert await charm(guest, zone) is None
        assert f"still_dwell:{zone}" not in (await player_row(guest))["flags"]

        async def interposed_tick(*args, **kwargs):
            await tick()
            assert await charm(guest, zone) is None
            return await party_level_warning(*args, **kwargs)

        with patch("travel_tools.party_level_warning", side_effect=interposed_tick):
            assert (await arrive(walk, "travel", origin))["arrived"]
        await arrive(walk, "move_player", zone)
        await advance(clock, tick, HOUR)
        assert rolls[-1] == (18, 0, 17)
        assert len(rolls) == 3 and await charm(guest, zone)
