"""Permanent death penalties survive recovery through the registered rest verb."""

import pytest
from acceptance.rest_walk import RestWalk

import db_mutations_resurrection


@pytest.mark.parametrize("penalty", [7, 100])
def test_long_rest_preserves_the_effective_hp_ceiling(harness, penalty):
    async def check():
        walk = await RestWalk().setup(harness)
        await walk.solo()
        await db_mutations_resurrection.apply_maxhp_override_delta(walk.player, -penalty)
        await db_mutations_resurrection.revive_player(walk.player, walk.sd.location_id, 1)
        receipt = await walk.command("long")
        assert not receipt.is_error, receipt.output
        row = await walk.row(walk.player)
        assert row["hp"] == {"current": max(1, 30 - penalty), "max": 30}
        assert row["maxhp_override"] == -penalty
        assert walk.events[0]["character"]["hp"] == row["hp"]

    harness.run_sync(check())
