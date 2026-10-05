"""Pin d20 checks but leave attack damage real; direct HP setup controls kill timing."""

from __future__ import annotations

import json
from unittest.mock import patch

from acceptance._capstone_helpers import (
    _build_state,
    _d20,
    _declare_attacks,
    _dice_events,
    _enemy,
    _player,
    _player_attack_events,
    _resolve_round,
    _start_combat,
)
from acceptance.seeds import seed_player
from sample_fixtures import make_context, make_mock_room

import combat_death_save
import db
import db_mutations

# --- AC1 + AC4: combat DICE_ROLL dramatic chain (evaluator -> packet -> event -> summary) ---


async def test_combat_nat20_crit_is_dramatic_chain(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    player_id = "cap_m45_nat20"
    room = make_mock_room()
    ctx = make_context(player_id, room=room)
    state = _build_state("combat_cap_m45_nat20", player_id, [_enemy("goblin_a", hp=100)])
    try:
        await _start_combat(pool, player_id, state, ctx)
        await _declare_attacks(ctx, player_id, "goblin_a", ["goblin_a"])
        with patch("check_resolution.dice_roll", return_value=_d20(20)):
            result = await _resolve_round(ctx)

        # Event side of the chain.
        attacks = _player_attack_events(room)
        assert attacks, "the player's attack emitted a DICE_ROLL"
        assert attacks[0]["dramatic"] is True
        assert attacks[0]["context"] == "natural_20"
        # Summary side of the chain (DM-facing packet from resolve_phase).
        assert not isinstance(result, tuple), "a non-lethal crit (enemy at 100 HP) loops the phase"
        summaries = result["packets"]
        dramatic_summaries = [p for p in summaries if p.get("dramatic") is True]
        assert dramatic_summaries, "the resolve packet summary carries the dramatic flag"
    finally:
        await db_mutations.delete_combat_state(state.combat_id, conn=pool)


async def test_combat_killing_blow_is_dramatic(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    player_id = "cap_m45_kill"
    room = make_mock_room()
    ctx = make_context(player_id, room=room)
    # Two enemies so the kill is NOT also the last enemy; target at 1 HP so a mid hit kills.
    state = _build_state("combat_cap_m45_kill", player_id, [_enemy("goblin_a", hp=1), _enemy("goblin_b", hp=100)])
    try:
        await _start_combat(pool, player_id, state, ctx)
        await _declare_attacks(ctx, player_id, "goblin_a", ["goblin_a", "goblin_b"])
        with patch("check_resolution.dice_roll", return_value=_d20(11)):
            await _resolve_round(ctx)

        attacks = _player_attack_events(room)
        assert attacks, "the player's attack emitted a DICE_ROLL"
        assert attacks[0]["dramatic"] is True
        assert attacks[0]["context"] == "killing_blow"
    finally:
        await db_mutations.delete_combat_state(state.combat_id, conn=pool)


async def test_combat_routine_hit_is_not_dramatic(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    player_id = "cap_m45_routine"
    room = make_mock_room()
    ctx = make_context(player_id, room=room)
    # first_attack already resolved + two healthy enemies => no first_attack/last_enemy promotion.
    state = _build_state(
        "combat_cap_m45_routine",
        player_id,
        [_enemy("goblin_a", hp=100), _enemy("goblin_b", hp=100)],
        first_attack_resolved=True,
    )
    try:
        await _start_combat(pool, player_id, state, ctx)
        await _declare_attacks(ctx, player_id, "goblin_a", ["goblin_a", "goblin_b"])
        with patch("check_resolution.dice_roll", return_value=_d20(11)):
            await _resolve_round(ctx)

        attacks = _player_attack_events(room)
        assert attacks, "the player's attack emitted a DICE_ROLL"
        assert attacks[0]["dramatic"] is False
        assert attacks[0]["context"] == ""
    finally:
        await db_mutations.delete_combat_state(state.combat_id, conn=pool)


# --- AC1: death saves are ALWAYS dramatic ---


async def test_death_save_is_always_dramatic(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    player_id = "cap_m45_deathsave"
    room = make_mock_room()
    ctx = make_context(player_id, room=room)
    fallen = _player(player_id, hp=0)
    fallen.hp_current = 0
    fallen.is_fallen = True
    state = _build_state("combat_cap_m45_deathsave", player_id, [_enemy("goblin_a", hp=20)])
    state.participants[0] = fallen
    try:
        await _start_combat(pool, player_id, state, ctx)
        response = json.loads(await combat_death_save._request_death_save_impl(ctx))

        assert response["dramatic"] is True
        assert response["context"] == "death_save"
        save_events = [e for e in _dice_events(room) if e.get("roll_type") == "death_save"]
        assert save_events, "the death save emitted a DICE_ROLL"
        assert save_events[0]["dramatic"] is True
        assert save_events[0]["context"] == "death_save"
    finally:
        await db_mutations.delete_combat_state(state.combat_id, conn=pool)


# --- AC2: out-of-combat skill check (nat-20 dramatic, routine not) ---


async def test_out_of_combat_skill_check_dramatic(reset_db_pool: str) -> None:
    import check_tools

    pool = await db.get_pool()
    player_id = "cap_m45_skill"
    await seed_player(pool, player_id=player_id, location_id="accord_guild_hall")

    room = make_mock_room()
    ctx = make_context(player_id, room=room)
    with patch("check_resolution.dice_roll", return_value=_d20(20)):
        await check_tools._check_skill_impl(ctx, "perception", "moderate", "scanning the hall")
    crit = next(e for e in _dice_events(room) if e.get("roll_type") == "skill_check")
    assert crit["dramatic"] is True
    assert crit["context"] == "natural_20"

    room2 = make_mock_room()
    ctx2 = make_context(player_id, room=room2)
    with patch("check_resolution.dice_roll", return_value=_d20(10)):
        await check_tools._check_skill_impl(ctx2, "perception", "moderate", "scanning the hall")
    routine = next(e for e in _dice_events(room2) if e.get("roll_type") == "skill_check")
    assert routine["dramatic"] is False
    assert routine["context"] == ""


# --- AC3: scarcity bar holds across a representative multi-phase fight ---


async def test_scarcity_bar_holds_over_representative_fight(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    player_id = "cap_m45_scarcity"
    room = make_mock_room()
    ctx = make_context(player_id, room=room)
    # goblin_a is whittled across the fight; goblin_b stays alive so goblin_a is never "last enemy".
    state = _build_state("combat_cap_m45_scarcity", player_id, [_enemy("goblin_a", hp=100), _enemy("goblin_b", hp=100)])
    try:
        await _start_combat(pool, player_id, state, ctx)
        with patch("check_resolution.dice_roll", return_value=_d20(11)):
            for phase in range(5):
                cs = ctx.userdata.combat_state
                if cs is None:  # defensive: a forced kill could end combat early
                    break
                # Force the killing blow onto the final phase by dropping goblin_a to 1 HP.
                if phase == 4:
                    next(p for p in cs.participants if p.id == "goblin_a").hp_current = 1
                await _declare_attacks(ctx, player_id, "goblin_a", ["goblin_a", "goblin_b"])
                await _resolve_round(ctx)

        player_attacks = _player_attack_events(room)
        assert len(player_attacks) >= 3, "the fight ran several phases of player attacks"
        dramatic_reveals = [e for e in player_attacks if e["dramatic"] is True]
        # Scarcity bar: at most two reveals (first_attack + the final killing_blow).
        assert 0 <= len(dramatic_reveals) <= 2, f"too many dramatic reveals: {[e['context'] for e in dramatic_reveals]}"
        # And the routine middle phases genuinely earned no dice.
        assert any(e["dramatic"] is False for e in player_attacks), "routine attacks stay non-dramatic"
    finally:
        await db_mutations.delete_combat_state(state.combat_id, conn=pool)
