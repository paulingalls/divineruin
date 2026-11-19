from acceptance.test_still_paradise_trap import command, row_snapshot
from acceptance.test_still_paradise_trap import paradise as paradise
from sample_fixtures import published_payloads

import db_mutations
from movement_tools import move_player
from still_charm import key


async def test_malformed_charm_refuses_departure_atomically(paradise):
    walk, origin, zone = paradise
    await db_mutations.set_player_flag(walk.players[1], key(origin), "{}")
    before, events = await row_snapshot(walk), published_payloads(walk.sd.room)
    refusal = await command(walk, move_player.id, zone)
    assert "Invalid Still charm record" in refusal
    assert await row_snapshot(walk) == before
    assert published_payloads(walk.sd.room) == events
    assert walk.sd.location_id == origin
