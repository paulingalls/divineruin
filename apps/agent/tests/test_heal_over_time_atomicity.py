"""Standalone combat end rolls back both durable and live Regenerate state."""

from unittest.mock import patch

from _spell_heal_fixtures import REGENERATE
from _spell_heal_fixtures import spell_heal_walk as spell_heal_walk
from sample_fixtures import published_payloads
from test_heal_over_time import cast_in_combat, set_hp

import db_mutations


async def test_failed_settlement_hp_write_keeps_the_live_condition_retryable(healer):
    await healer.prepare(REGENERATE)
    ally = await cast_in_combat(healer)
    await set_hp(healer, ally, 10)
    await healer.register_end()
    before = (await healer.checkpoint()).to_dict()
    events = published_payloads(healer.sd.room)
    update_hp = db_mutations.update_player_hp
    written = []

    async def fail_after_write(pid, hp, *, conn):
        await update_hp(pid, hp, conn=conn)
        written.append((pid, (await healer.read(pid, conn=conn))["hp"]["current"]))
        raise ConnectionError("injected failure after settling regeneration")

    with patch.object(db_mutations, "update_player_hp", side_effect=fail_after_write):
        await healer.command("end_combat", {"outcome": "fled"}, error=True)
    assert written == [(ally, 40)]
    assert (await healer.read(ally))["hp"]["current"] == 10
    checkpoint = await db_mutations.load_combat_state(before["combat_id"])
    assert checkpoint is not None and checkpoint.to_dict() == before
    assert healer.fight_state.to_dict() == before
    assert published_payloads(healer.sd.room) == events

    await healer.command("end_combat", {"outcome": "fled"})
    assert healer.sd.combat_state is None
    assert (await healer.read(ally))["hp"]["current"] == 40
    assert (
        published_payloads(healer.sd.room)[len(events) :].count({"type": "hp_changed", "current": 40, "max": 40}) == 1
    )
