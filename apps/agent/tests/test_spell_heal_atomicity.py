"""A failed real HP update rolls back the whole registered exploration cast."""

from unittest.mock import patch

from _spell_heal_fixtures import WOUNDS
from _spell_heal_fixtures import spell_heal_walk as spell_heal_walk
from sample_fixtures import published_payloads

import db_mutations
import spells


async def test_failure_after_hp_write_rolls_back_focus_hp_mirrors_and_events(healer):
    await healer.prepare(WOUNDS)
    ally = await healer.add_player()
    args = {"id": WOUNDS, "target_id": ally}
    cost = spells.get_spell(WOUNDS).focus_cost
    before = await healer.row(), await healer.read(ally), healer.sd.party.to_dict(), published_payloads(healer.sd.room)
    update_hp = db_mutations.update_player_hp
    observed = []

    async def fail_after_write(pid, hp, *, conn):
        await update_hp(pid, hp, conn=conn)
        caster = await healer.read(healer.player, conn=conn)
        recipient = await healer.read(ally, conn=conn)
        observed.append((caster["focus"]["current"], recipient["hp"]["current"]))
        raise ConnectionError("injected failure after the heal update")

    with patch.object(db_mutations, "update_player_hp", side_effect=fail_after_write):
        await healer.command("activate", args, error=True)
    assert len(observed) == 1
    remaining, written_hp = observed[0]
    assert remaining == 30 - cost and written_hp > 3
    assert (
        await healer.row(),
        await healer.read(ally),
        healer.sd.party.to_dict(),
        published_payloads(healer.sd.room),
    ) == before

    result = await healer.command("activate", args)
    assert await healer.focus() == 30 - cost
    assert (await healer.read(ally))["hp"]["current"] == result["healing_results"][0]["hp_current"] > 3
