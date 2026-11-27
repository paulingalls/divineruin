"""Patch only the d20; execute real producers, consumers and persistence."""

from __future__ import annotations

import json
from unittest.mock import patch

from acceptance._capstone_helpers import _d20
from acceptance._spell_hostile_condition_helpers import add_player, cast_spell, defend, play, reload, set_foe
from acceptance._spell_hostile_condition_helpers import dev_db_pool as dev_db_pool
from acceptance.seeds import seed_player
from acceptance.test_spell_bless_lifecycle import BLESS, context, save_total
from combat.test_spell_damage_lands import spell_fight as spell_fight
from sample_fixtures import make_context, make_mock_room
from voice_condition_fixtures import participant

import condition_produce
import db
import db_mutations_conditions
import db_queries
from check_tools import _check_save_impl
from combat_prompts import COMBAT_PROMPT


def _types(conds: list[dict]) -> list[str]:
    return [c["type"] for c in conds]


async def _read_types(pool, player_id: str) -> list[str]:
    return _types(await db_mutations_conditions.read_player_conditions(player_id, conn=pool))


async def _produce(
    pool,
    caster_id,
    condition,
    source,
    *,
    target_id=None,
    target_ids=None,
    party_member_ids=None,
    companion_id=None,
) -> list[str]:
    """Land a beneficial condition through the REAL OOC producer (cast/ability landing helper).

    ``party_member_ids`` (M4.8 story-007 party gate) defaults to the caster plus every requested
    target — every capstone target is a seeded party ally, admitted via the party path — unless a
    caller opts into the companion allowlist instead via ``companion_id``.
    """
    caster_row = await db_queries.get_player(caster_id, conn=pool)
    assert caster_row is not None
    if party_member_ids is None:
        targets = target_ids if target_ids else ([target_id] if target_id is not None else [])
        party_member_ids = [caster_id, *targets]
    return await condition_produce.produce_ooc_condition(
        condition,
        source,
        target_id=target_id,
        target_ids=target_ids,
        caster_row=caster_row,
        caster_id=caster_id,
        party_member_ids=party_member_ids,
        companion_id=companion_id,
        conn=pool,
    )


async def test_inspire_folds_once_then_expires(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    caster_id, ally_id, base_id = "cap_m48_bard", "cap_m48_insp_ally", "cap_m48_insp_base"
    for pid in (caster_id, ally_id, base_id):
        await seed_player(pool, player_id=pid, location_id="accord_guild_hall")
    try:
        await _produce(pool, caster_id, "inspired", "bard_inspire", target_id=ally_id)
        assert "inspired" in await _read_types(pool, ally_id)

        ctx = make_context(ally_id, room=make_mock_room())
        ctx_base = make_context(base_id, room=make_mock_room())
        with patch("check_resolution.dice_roll", return_value=_d20(10)):
            first = json.loads(await _check_save_impl(ctx, "wisdom", 12, "resist"))
            baseline = json.loads(await _check_save_impl(ctx_base, "wisdom", 12, "resist"))
            second = json.loads(await _check_save_impl(ctx, "wisdom", 12, "resist"))

        assert first["total"] > baseline["total"]  # +1d4 applied once
        assert "inspired" not in await _read_types(pool, ally_id)  # consumed
        assert second["total"] == baseline["total"]  # expired: the second roll gets no die
    finally:
        for pid in (caster_id, ally_id, base_id):
            await pool.execute("DELETE FROM players WHERE player_id = $1", pid)


async def test_engine_auto_save_never_consumes(spell_fight):
    ctx = spell_fight
    recipient = ctx.userdata.player_id
    bard = await add_player(ctx, "bard")
    foe = await set_foe(ctx, "cult_leader")
    await play(
        ctx, cast_spell(recipient, BLESS, recipient), cast_spell(bard, "bard_inspire", recipient), defend(foe.id)
    )

    with patch("condition_bonus.dice_roll", return_value=_d20(3)):
        packets, state = await play(
            ctx, defend(recipient), defend(bard), cast_spell(foe.id, "Hold Person", recipient), face=12
        )
    enemy = next(packet for packet in packets if packet["actor_id"] == foe.id)
    assert (enemy["save_roll"], enemy["save_total"], enemy["save_success"]) == (12, 19, True)
    assert set(_types(participant(state, recipient).conditions)) == {"blessed", "inspired"}

    chosen = context(recipient)
    chosen.userdata.combat_state = state
    assert await save_total(recipient, ctx=chosen) == 17
    state = await reload(ctx)
    assert _types(participant(state, recipient).conditions) == ["blessed"]
    chosen.userdata.combat_state = state
    assert await save_total(recipient, ctx=chosen) == 14


async def test_multitarget_bless_voices_every_ally(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    caster_id = "cap_m48_mt_caster"
    ally_a, ally_b = "cap_m48_mt_a", "cap_m48_mt_b"
    for pid in (caster_id, ally_a, ally_b):
        await seed_player(pool, player_id=pid, location_id="accord_guild_hall")
    try:
        voiced = await _produce(pool, caster_id, "blessed", "divine_bless", target_ids=[ally_a, ally_b])
        assert set(voiced) == {ally_a, ally_b}  # every ally named, not just one
        assert "blessed" in await _read_types(pool, ally_a)
        assert "blessed" in await _read_types(pool, ally_b)
        # The beat consumer (the DM, per the Beat-3 prompt) is instructed to read condition_targets.
        lowered = COMBAT_PROMPT.lower()
        assert "condition_targets" in lowered or "condition_applied" in lowered
    finally:
        for pid in (caster_id, ally_a, ally_b):
            await pool.execute("DELETE FROM players WHERE player_id = $1", pid)
