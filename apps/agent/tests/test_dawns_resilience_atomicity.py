"""A failure after the follower's HP write rolls back the whole heal."""

from unittest.mock import patch

import pytest
from _item_heal_fixtures import heal_roll
from _item_heal_fixtures import item_heal_walk as item_heal_walk
from _spell_heal_fixtures import WOUNDS
from sample_fixtures import published_payloads
from test_dawns_resilience import prepare_follower

import db_mutations
import spells


@pytest.mark.parametrize("combat", [False, True])
async def test_bonus_write_rolls_back_with_the_underlying_heal(walk, combat):
    await prepare_follower(walk, WOUNDS)
    ally = await walk.add_player()
    if combat:
        await walk.fight()
        await walk.declare(WOUNDS, [ally])

    async def snapshot():
        return (
            await walk.row(),
            await walk.read(ally),
            walk.sd.party.to_dict(),
            (await walk.checkpoint()).to_dict() if combat else walk.sd.combat_state,
            published_payloads(walk.sd.room),
        )

    before = await snapshot()
    write_hp = db_mutations.update_player_hp
    observed = []

    async def fail_after_bonus(pid, hp, *, conn):
        await write_hp(pid, hp, conn=conn)
        if pid == walk.player:
            healer = await walk.read(pid, conn=conn)
            recipient = await walk.read(ally, conn=conn)
            observed.append((healer["hp"]["current"], recipient["hp"]["current"], healer["focus"]["current"]))
            raise ConnectionError("injected failure after Dawn's Resilience")

    with heal_roll(5), patch.object(db_mutations, "update_player_hp", side_effect=fail_after_bonus):
        if combat:
            await walk.command("resolve_phase", {}, error=True)
        else:
            await walk.command("activate", {"id": WOUNDS, "target_id": ally}, error=True)

    assert observed == [(12, 14, 30 - spells.get_spell(WOUNDS).focus_cost)]
    assert await snapshot() == before
