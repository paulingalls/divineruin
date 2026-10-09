"""Field receipts, damage and events commit together across public retries."""

import copy
from unittest.mock import patch

import pytest
from acceptance.test_mawling_dissolution_field import (
    drain,
    grapple,
    next_round,
    persist,
)
from acceptance.test_mawling_dissolution_field import (
    field_dice as field_dice,
)
from acceptance.test_mawling_dissolution_field import (
    maw as maw,
)
from acceptance.test_mawling_dissolution_field import (
    mock_combat_agent_factory as mock_combat_agent_factory,
)

import db_mutations
import db_queries


@pytest.mark.parametrize("maw", [{"companion": True, "gear": True}], indirect=True)
async def test_failure_after_state_write_rolls_back_and_retries_once(maw, field_dice):
    companion = maw.sd.companion
    await maw.command(
        "declare_phase",
        {
            "declarations": [
                {
                    "kind": "attack",
                    "actor_id": eid,
                    "action": "Lunge",
                    "target_id": target,
                    "held_item_id": "",
                    "rider": "",
                }
                for eid, target in zip(maw.enemies, [maw.players[0], companion.id], strict=True)
            ]
        },
    )
    await drain(maw)
    victim = maw.sd.combat_state.get_participant(maw.players[0])
    victim.hp_current = 1
    maw.sd.combat_state.get_participant(companion.id).hp_current = 1
    import db_mutations_concentration

    maw.sd.member_state(victim.id).concentration.spell_id = "divine_bless"
    await db_mutations_concentration.update_player_concentration(victim.id, "divine_bless")
    await persist(maw)
    await maw.command("declare_phase", {"declarations": [{"kind": "defend", "actor_id": maw.players[1]}]})
    before = await maw.snapshot()
    events = maw.sd.room.local_participant.publish_data.call_count
    scratch = copy.deepcopy((maw.sd.recent_events, companion, maw.sd.member_state(victim.id).concentration))
    inventory = await db_queries.get_player_inventory(victim.id)
    save = db_mutations.save_combat_state

    async def fail_after_write(*args, **kwargs):
        await save(*args, **kwargs)
        raise RuntimeError("injected field checkpoint failure")

    with patch("db_mutations.save_combat_state", side_effect=fail_after_write):
        await maw.command("resolve_phase", {}, error=True)
    assert await maw.snapshot() == before
    assert (maw.sd.recent_events, maw.sd.companion, maw.sd.member_state(victim.id).concentration) == scratch
    assert await db_queries.get_player_inventory(victim.id) == inventory
    assert maw.sd.room.local_participant.publish_data.call_count == events
    first = await maw.command("resolve_phase", {})
    assert sum(p.get("automatic", False) for p in first["packets"]) == 2
    state = await maw.reload()
    assert state.turn_start_receipts[victim.id] == state.round_number
    assert state.get_participant(victim.id).hp_current == 0
    row = await db_queries.get_player(victim.id)
    assert row is not None and row["hp"]["current"] == 0
    assert not any(p.get("automatic") for p in await drain(maw))
    assert await db_queries.get_player_inventory(victim.id) != inventory
    assert not maw.sd.companion.is_conscious
    assert maw.sd.member_state(victim.id).concentration.spell_id is None
    assert field_dice[0].call_count == 4  # The rolled-back roll is retried, never committed twice.


@pytest.mark.parametrize("maw", [{"reactions": True}], indirect=True)
async def test_multiattack_reloads_do_not_repeat_field(maw, field_dice):
    victim = await grapple(maw)
    before = victim.hp_current
    await maw.declare([maw.players[0]] * 2)
    first = await maw.command("resolve_phase", {})
    assert sum(p.get("automatic", False) for p in first["packets"]) == 1
    await maw.reload()
    paused = await maw.command("resolve_phase", {})
    assert paused["next"]["waiting_on"] is not None
    assert not any(p.get("automatic") for p in paused["packets"])
    await maw.reload()
    assert not any(p.get("automatic") for p in await drain(maw))
    assert maw.sd.combat_state.get_participant(victim.id).hp_current == before - 12
    assert sum(p.get("automatic", False) for p in await next_round(maw)) == 1
    assert field_dice[0].call_count == 2
