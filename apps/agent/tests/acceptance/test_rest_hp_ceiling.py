"""Permanent death penalties survive recovery through the registered rest verb."""

import json

import pytest
from acceptance.rest_walk import RestWalk

import db_mutations_resurrection


@pytest.mark.parametrize("penalty", [7, 100])
def test_long_rest_preserves_the_effective_hp_ceiling(harness, penalty):
    async def check():
        walk = await RestWalk().setup(harness)
        await walk.solo()
        await walk.pool.execute(
            "UPDATE players SET data=jsonb_set(data, '{divine_favor}', $2::jsonb) WHERE player_id=$1",
            walk.player,
            json.dumps({"patron": "kaelen", "level": 0, "max": 100, "last_whisper_level": 0}),
        )
        maximum = max(1, 35 - penalty)
        walk.primary_hp_max = maximum
        await db_mutations_resurrection.apply_maxhp_override_delta(walk.player, -penalty)
        await db_mutations_resurrection.revive_player(walk.player, walk.sd.location_id, 1)
        short = await walk.command("short")
        assert not short.is_error, short.output
        assert (await walk.row(walk.player))["hp"] == {"current": 1, "max": 30}
        walk.events.clear()
        receipt = await walk.command("long")
        assert not receipt.is_error, receipt.output
        row = await walk.row(walk.player)
        assert row["hp"] == {"current": maximum, "max": 30}
        assert row["maxhp_override"] == -penalty
        assert walk.events[0]["character"]["hp"] == {"current": maximum, "max": maximum}

    harness.run_sync(check())
