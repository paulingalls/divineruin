from unittest.mock import patch

import pytest
from _item_heal_fixtures import heal_roll
from _item_heal_fixtures import item_heal_walk as item_heal_walk
from sample_fixtures import published_payloads

import db_mutations
import db_queries


@pytest.mark.parametrize("combat", [False, True])
async def test_failure_after_the_real_hp_write_rolls_back_the_item_heal(walk, combat):
    await walk.put()
    ally = await walk.add_player(hp=5)
    if combat:
        await walk.fight()
        await walk.declare_item(target=ally)

    async def snapshot():
        return (
            await walk.read(ally),
            await db_queries.get_inventory_snapshot(walk.player),
            (await walk.checkpoint()).to_dict() if combat else walk.sd.combat_state,
            walk.sd.party.to_dict(),
            published_payloads(walk.sd.room),
        )

    before = await snapshot()
    write_hp = db_mutations.update_player_hp
    observed = []

    async def fail_after_write(pid, hp, *, conn):
        await write_hp(pid, hp, conn=conn)
        observed.append(((await walk.read(ally, conn=conn))["hp"]["current"], await walk.quantity(conn=conn)))
        raise ConnectionError("injected failure after the item heal update")

    with heal_roll(7):
        with patch.object(db_mutations, "update_player_hp", side_effect=fail_after_write):
            if combat:
                await walk.command("resolve_phase", {}, error=True)
            else:
                await walk.consume(target=ally, error=True)
        assert observed == [(12, 1)]
        assert await snapshot() == before
        result = await walk.resolve_item() if combat else await walk.consume(target=ally)
    assert result["healing_results"][0]["hp_current"] == (await walk.read(ally))["hp"]["current"] == 12
    assert await walk.quantity() == 1
