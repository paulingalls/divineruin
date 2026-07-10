"""Capstone: M4.3 status conditions end-to-end against a real Postgres testcontainer.

Stories 001-005 shipped the pieces: the pure 21-condition catalog + apply/remove/tick/aggregate
(001), the Beat-4 wrap tick (002), condition modifiers feeding checks/attacks/saves (003), JSONB
persistence + combat-end merge (004), and the client icons + Beat-3 exhaustion narration (005).
This capstone proves they COMPOSE on ONE seeded testcontainer (auto-marked `acceptance` by
tests/acceptance/conftest.py): a condition's modifier folds into the REAL attack resolver
(AC1), the Beat-4 wrap ticks conditions — duration expiry + Frightened's save-to-clear — and the
change persists to the combat SSOT (AC2), and a persists_across_encounters condition survives the
end of the fight in players.data.conditions (AC3).

Determinism: every d20 (attack / save) routes through check_resolution._roll_d20_check, which reads
the module-global check_resolution.dice_roll. Patching that one seam forces the d20 while the real
conditions module, resolvers, and engine run end to end (an honest chain, not a hand-built verdict).
Attack DAMAGE uses the separate check_resolution_attack.dice_roll (left real); kill timing is
controlled by setting a participant's hp_current directly. Each test uses a distinct player_id /
combat_id since the testcontainer DB is shared.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from acceptance._capstone_helpers import _build_state, _d20, _declare_attacks, _enemy, _start_combat
from sample_fixtures import make_context, make_mock_room

import combat_turn
import conditions
import db
import db_mutations
import db_mutations_conditions


def _player_packet(result: str) -> dict:
    """The player's resolution packet summary from a (non-ending) resolve_phase JSON response."""
    packets = json.loads(result)["packets"]
    return next(p for p in packets if p["attacker"] == "Kael")


# --- AC1: a condition's modifier folds into the REAL attack resolver ---


async def test_exhausted_modifier_folds_into_real_attack(reset_db_pool: str) -> None:
    """Exhausted (2 stacks, check_modifier -1/stack) lowers a forced-d20 attack total by EXACTLY 2
    versus the same attack with no condition — proving the real get_condition_effects ->
    _apply_condition_modifiers -> attack resolver chain, not a hand-built number."""
    pool = await db.get_pool()

    # Clean baseline.
    clean_id = "cap_m43_attack_clean"
    clean_state = _build_state("combat_cap_m43_attack_clean", clean_id, [_enemy("goblin_a", hp=100)])
    ctx_clean = make_context(clean_id, room=make_mock_room())
    # Exhausted x2.
    exh_id = "cap_m43_attack_exhausted"
    exh_state = _build_state("combat_cap_m43_attack_exhausted", exh_id, [_enemy("goblin_a", hp=100)])
    exh_player = exh_state.get_participant(exh_id)
    assert exh_player is not None
    exh_player.conditions = conditions.apply_condition(exh_player.conditions, "exhausted", source="forced_march")
    exh_player.conditions = conditions.apply_condition(exh_player.conditions, "exhausted", source="forced_march")
    assert conditions.get_condition_effects(exh_player.conditions).check_modifier == -2

    try:
        await _start_combat(pool, clean_id, clean_state, ctx_clean)
        await _declare_attacks(ctx_clean, clean_id, "goblin_a", ["goblin_a"])
        with patch("check_resolution.dice_roll", return_value=_d20(10)):
            clean_result = await combat_turn._resolve_phase_impl(ctx_clean)

        ctx_exh = make_context(exh_id, room=make_mock_room())
        await _start_combat(pool, exh_id, exh_state, ctx_exh)
        await _declare_attacks(ctx_exh, exh_id, "goblin_a", ["goblin_a"])
        with patch("check_resolution.dice_roll", return_value=_d20(10)):
            exh_result = await combat_turn._resolve_phase_impl(ctx_exh)

        assert isinstance(clean_result, str) and isinstance(exh_result, str)  # non-ending phases loop
        clean_total = _player_packet(clean_result)["attack_total"]
        exh_total = _player_packet(exh_result)["attack_total"]
        # Same forced d20, same weapon/attributes — the only delta is Exhausted's -1/stack.
        assert clean_total - exh_total == 2, f"clean={clean_total} exhausted={exh_total}"
    finally:
        await db_mutations.delete_combat_state(clean_state.combat_id, conn=pool)
        await db_mutations.delete_combat_state(exh_state.combat_id, conn=pool)


# --- AC2: Beat-4 wrap ticks — duration expiry + save-to-clear — and persists to the combat SSOT ---


async def test_beat4_wrap_expires_and_clears_then_persists(reset_db_pool: str) -> None:
    """A forced-success WIS save clears Frightened at the Beat-4 wrap and Stunned (duration 1) expires;
    BOTH disappear from the participant AND from the persisted combat_instances SSOT (reloaded from DB)."""
    pool = await db.get_pool()
    player_id = "cap_m43_tick_clear"
    state = _build_state("combat_cap_m43_tick_clear", player_id, [_enemy("goblin_a", hp=100)])
    player = state.get_participant(player_id)
    assert player is not None
    player.conditions = conditions.apply_condition(player.conditions, "stunned", duration=1, source="mace")
    player.conditions = conditions.apply_condition(player.conditions, "frightened", source="wraith")
    ctx = make_context(player_id, room=make_mock_room())
    try:
        await _start_combat(pool, player_id, state, ctx)
        await _declare_attacks(ctx, player_id, "goblin_a", ["goblin_a"])
        with patch("check_resolution.dice_roll", return_value=_d20(20)):  # WIS save succeeds (>= DC 10)
            await combat_turn._resolve_phase_impl(ctx)

        # In-memory participant: Stunned expired, Frightened cleared by the made save.
        live = ctx.userdata.combat_state.get_participant(player_id)
        assert live is not None
        assert [c["type"] for c in live.conditions] == []

        # SSOT: the same change round-tripped through the phase tx into combat_instances JSONB.
        reloaded = await db_mutations.load_combat_state(state.combat_id, conn=pool)
        assert reloaded is not None
        reloaded_player = reloaded.get_participant(player_id)
        assert reloaded_player is not None
        assert [c["type"] for c in reloaded_player.conditions] == []
    finally:
        await db_mutations.delete_combat_state(state.combat_id, conn=pool)


async def test_beat4_failed_save_keeps_frightened(reset_db_pool: str) -> None:
    """A forced-failure WIS save leaves Frightened in place (save-to-clear is real, not unconditional),
    while the duration-1 Stunned still expires — the persisted SSOT reflects exactly that."""
    pool = await db.get_pool()
    player_id = "cap_m43_tick_fail"
    state = _build_state("combat_cap_m43_tick_fail", player_id, [_enemy("goblin_a", hp=100)])
    player = state.get_participant(player_id)
    assert player is not None
    player.conditions = conditions.apply_condition(player.conditions, "stunned", duration=1, source="mace")
    player.conditions = conditions.apply_condition(player.conditions, "frightened", source="wraith")
    ctx = make_context(player_id, room=make_mock_room())
    try:
        await _start_combat(pool, player_id, state, ctx)
        await _declare_attacks(ctx, player_id, "goblin_a", ["goblin_a"])
        with patch("check_resolution.dice_roll", return_value=_d20(1)):  # WIS save fails (< DC 10)
            await combat_turn._resolve_phase_impl(ctx)

        reloaded = await db_mutations.load_combat_state(state.combat_id, conn=pool)
        assert reloaded is not None
        reloaded_player = reloaded.get_participant(player_id)
        assert reloaded_player is not None
        types = [c["type"] for c in reloaded_player.conditions]
        assert types == ["frightened"], types  # Stunned expired, Frightened persists on the failed save
    finally:
        await db_mutations.delete_combat_state(state.combat_id, conn=pool)


# --- AC3: a persists_across_encounters condition survives the end of the fight ---


async def test_persistent_condition_survives_combat_end(reset_db_pool: str) -> None:
    """When the last enemy falls, Exhausted (persists_across_encounters) is written to
    players.data.conditions and is retrievable afterward; a non-persistent condition (Blinded) is not."""
    pool = await db.get_pool()
    player_id = "cap_m43_persist"
    # Single enemy at 1 HP so a forced hit drops it and combat ends (victory handoff).
    state = _build_state("combat_cap_m43_persist", player_id, [_enemy("goblin_a", hp=1)])
    player = state.get_participant(player_id)
    assert player is not None
    player.conditions = conditions.apply_condition(player.conditions, "exhausted", source="forced_march")
    player.conditions = conditions.apply_condition(player.conditions, "exhausted", source="forced_march")
    player.conditions = conditions.apply_condition(player.conditions, "blinded", source="ash")  # not persistent
    ctx = make_context(player_id, room=make_mock_room())
    try:
        await _start_combat(pool, player_id, state, ctx)
        await _declare_attacks(ctx, player_id, "goblin_a", ["goblin_a"])
        with patch("check_resolution.dice_roll", return_value=_d20(20)):
            result = await combat_turn._resolve_phase_impl(ctx)
        assert isinstance(result, tuple), "dropping the last enemy ends combat (handoff tuple)"

        stored = await db_mutations_conditions.read_player_conditions(player_id, conn=pool)
        by_type = {c["type"]: c for c in stored}
        assert "exhausted" in by_type, stored
        assert by_type["exhausted"]["stacks"] == 2
        assert "blinded" not in by_type, "a non-persistent condition must not survive the encounter"
    finally:
        await db_mutations.delete_combat_state(state.combat_id, conn=pool)
