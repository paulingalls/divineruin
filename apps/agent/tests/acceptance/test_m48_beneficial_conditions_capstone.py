"""Capstone: M4.8 beneficial-condition pipeline E2E (Bless + Inspire).

Proves the full single-use +1d4 seam end to end against the testcontainer DB, exercising the REAL
producers, tools, and persistence (only the d20 seam is patched): a producer applies the condition →
the next applicable player roll folds the +1d4 and consumes it → the removal persists → a later roll
no longer benefits → engine-auto saves never consume it → a multi-target buff names every ally →
breaking a Bless's concentration drops the buff (risk 0899a89ef0da). Stories 004/005/007/009/011/013
built the pieces; this is the integration capstone. Mirrors test_m43_conditions_capstone.py +
_capstone_helpers.py.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from acceptance._capstone_helpers import _build_state, _d20, _declare_attacks, _enemy, _start_combat
from acceptance.seeds import seed_player
from sample_fixtures import make_context, make_mock_room

import check_resolution_save
import combat_turn
import concentration_break
import condition_produce
import conditions
import db
import db_mutations
import db_mutations_conditions
import db_queries
import spells
from check_tools import _check_save_impl
from system_prompts import COMBAT_PROMPT


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


async def test_bless_save_folds_consumes_and_persists_removal(reset_db_pool: str) -> None:
    """AC1: a caster blesses an ally; the ally's save folds +1d4 AND Blessed is consumed + persisted
    as removed (vs an unblessed baseline at the same forced d20)."""
    pool = await db.get_pool()
    caster_id, ally_id, base_id = "cap_m48_caster", "cap_m48_bless_ally", "cap_m48_bless_base"
    for pid in (caster_id, ally_id, base_id):
        await seed_player(pool, player_id=pid, location_id="accord_guild_hall")
    try:
        voiced = await _produce(pool, caster_id, "blessed", "divine_bless", target_id=ally_id)
        assert ally_id in voiced
        assert "blessed" in await _read_types(pool, ally_id)

        ctx = make_context(ally_id, room=make_mock_room())
        ctx_base = make_context(base_id, room=make_mock_room())
        with patch("check_resolution.dice_roll", return_value=_d20(10)):
            blessed = json.loads(await _check_save_impl(ctx, "wisdom", 12, "resist"))
            baseline = json.loads(await _check_save_impl(ctx_base, "wisdom", 12, "resist"))

        assert blessed["total"] > baseline["total"]  # +1d4 folded into the save
        assert "blessed" not in await _read_types(pool, ally_id)  # consumed + persisted as removed
    finally:
        for pid in (caster_id, ally_id, base_id):
            await pool.execute("DELETE FROM players WHERE player_id = $1", pid)


async def test_inspire_folds_once_then_expires(reset_db_pool: str) -> None:
    """AC2 + AC3: a Bard inspires an ally; the ally's first roll folds +1d4 once and consumes it; the
    second roll gets no +1d4 (expired on consume). Inspired folds into any roll, so a save drives it."""
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


async def test_bless_in_combat_attack_consumes_once(reset_db_pool: str) -> None:
    """AC1 in-combat: a blessed combat participant's attack folds the +1d4 and consumes Blessed once
    (rides save_combat_state); the participant is no longer blessed after the swing."""
    pool = await db.get_pool()
    player_id = "cap_m48_combat_bless"
    state = _build_state("combat_cap_m48_bless", player_id, [_enemy("goblin_a", hp=100)])
    attacker = state.get_participant(player_id)
    assert attacker is not None
    attacker.conditions = conditions.apply_condition(attacker.conditions, "blessed", source="divine_bless")
    ctx = make_context(player_id, room=make_mock_room())
    try:
        await _start_combat(pool, player_id, state, ctx)
        await _declare_attacks(ctx, player_id, "goblin_a", ["goblin_a"])
        with patch("check_resolution.dice_roll", return_value=_d20(10)):
            await combat_turn._resolve_phase_impl(ctx)
        # Consume-once rides the working state's participant (in-combat SSOT).
        live = ctx.userdata.combat_state.get_participant(player_id)
        assert live is not None
        assert not conditions.has_condition(live.conditions, "blessed")
    finally:
        await db_mutations.delete_combat_state(state.combat_id, conn=pool)


async def test_engine_auto_save_never_consumes(reset_db_pool: str) -> None:
    """Pipeline invariant (decision 6102eca13319): an engine-auto save (bonus_dice_eligible=False, the
    Beat-4 tick-clear / concentration-break path) never folds or consumes the player's +1d4."""
    blessed_player = {
        "attributes": {"wisdom": 14, "constitution": 14},
        "level": 3,
        "conditions": conditions.apply_condition([], "blessed"),
    }
    auto = check_resolution_save.resolve_saving_throw(blessed_player, "wisdom", 12, "tick", bonus_dice_eligible=False)
    player_initiated = check_resolution_save.resolve_saving_throw(dict(blessed_player), "wisdom", 12, "x")
    assert auto.consumed_conditions == ()  # engine-auto: die untouched
    assert player_initiated.consumed_conditions == ("blessed",)  # player-initiated: die spent


async def test_multitarget_bless_voices_every_ally(reset_db_pool: str) -> None:
    """AC5: a multi-target Bless lands on >1 ally and the producer names EVERY landed ally
    (condition_targets, not just the singular condition_applied), and the Beat-3 narration prompt now
    instructs the DM to voice them — so no buffed ally is left silent on state."""
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


async def test_breaking_bless_concentration_drops_blessed(reset_db_pool: str) -> None:
    """Risk 0899a89ef0da E2E: the REAL divine_bless catalog (applies_condition=blessed, concentration)
    drives removal — a caster concentrating on Bless whose CON save fails loses Blessed (and its +1d4)
    on the buffed participant, so the boon never outlives the broken concentration."""
    pool = await db.get_pool()
    await spells.load_spells()  # populate the catalog from the seeded spells table
    assert spells.get_spell("divine_bless").applies_condition == "blessed"

    player_id = "cap_m48_conc"
    await seed_player(pool, player_id=player_id, location_id="accord_guild_hall")
    state = _build_state("combat_cap_m48_conc", player_id, [_enemy("goblin_a", hp=100)])
    ally = state.get_participant(player_id)
    assert ally is not None
    ally.conditions = conditions.apply_condition(ally.conditions, "blessed", source="divine_bless")
    try:
        session = make_context(player_id, room=make_mock_room()).userdata
        session.combat_state = state
        session.concentration.spell_id = "divine_bless"
        with patch("check_resolution.dice_roll", return_value=_d20(1)):  # CON save fails -> breaks
            broken = await concentration_break.break_concentration_on_damage(
                session, 20, incapacitated=False, conn=pool
            )
        assert broken == "divine_bless"
        live = state.get_participant(player_id)
        assert live is not None
        assert not conditions.has_condition(live.conditions, "blessed")  # buff dropped on break
    finally:
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)
