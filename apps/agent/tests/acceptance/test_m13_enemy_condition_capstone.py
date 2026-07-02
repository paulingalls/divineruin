"""Capstone: M13 Enemy Condition Infliction end-to-end against a real Postgres testcontainer.

story-001 (content + fail-loud validation) and story-002 (resolve path, homes debt
f9a5d1e88432) shipped the M13 chain in slices with unit / mock-conn coverage. This capstone
proves they COMPOSE against ONE seeded testcontainer (auto-marked `acceptance`), driving the
REAL pipeline: content-driven `combat_init._start_combat_impl` builds participants from the
seeded `hollow_patrol_greyvale` encounter (running `_validate_enemy_action_conditions`), the
declare/resolve loop dispatches the enemy `hollow_rend_1`'s "Hollow Shriek" ABILITY through
`combat_packet._resolve_one_packet` to `combat_ability._resolve_enemy_condition_packet`, which
rolls the target's save and lands the condition via the immunity-gated `apply_condition` SSOT.

Determinism: the only seam patched is the d20 (check_resolution.dice_roll -> face 1, so every
save FAILS, including the Beat-4 tick-clear save — the landed condition survives the phase).
The two `hollow_drift` minions are omitted from declarations so they take no action and the
player takes no damage, keeping combat open (a JSON string result, not the end_combat tuple).
"""

from __future__ import annotations

import json
from unittest.mock import patch

from acceptance._capstone_helpers import _d20
from acceptance.seeds import seed_player
from sample_fixtures import make_context, make_mock_room

import combat_init
import combat_turn
import conditions
import db
import db_mutations

_ENCOUNTER = "hollow_patrol_greyvale"
_ENEMY_ID = "hollow_rend_1"
_ABILITY = "Hollow Shriek"


async def _start_and_declare(ctx, player_id: str) -> None:
    await combat_init._start_combat_impl(ctx, _ENCOUNTER, "The Hollow patrol turns.")
    decls = {
        player_id: {"type": "defend"},
        _ENEMY_ID: {"type": "ability", "action": _ABILITY, "target_id": player_id},
    }
    await combat_turn._declare_phase_impl(ctx, decls)


async def test_m13_hostile_condition_lands_through_real_combat_phase(reset_db_pool: str) -> None:
    """AC1: seeded encounter enemy action inflicts a hostile condition via a real combat phase."""
    pool = await db.get_pool()
    player_id = "cap_m13_lands"
    await seed_player(pool, player_id=player_id, location_id="accord_guild_hall")

    ctx = make_context(player_id, room=make_mock_room())
    state = None
    try:
        await _start_and_declare(ctx, player_id)
        state = ctx.userdata.combat_state

        with patch("check_resolution.dice_roll", return_value=_d20(1)):  # nat-1 -> save FAILS
            result = await combat_turn._resolve_phase_impl(ctx)

        assert isinstance(result, str), "combat continues (minions omitted -> no player damage)"
        payload = json.loads(result)
        enemy_packet = next(p for p in payload["packets"] if p["actor_id"] == _ENEMY_ID)
        assert enemy_packet["condition_applied"] == "frightened"

        live = ctx.userdata.combat_state.get_participant(player_id)
        assert live is not None
        assert conditions.has_condition(live.conditions, "frightened") is True
    finally:
        if state is not None:
            await db_mutations.delete_combat_state(state.combat_id, conn=pool)
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)


async def test_m13_temporary_hollowed_target_no_ops_the_immunity_gate(reset_db_pool: str) -> None:
    """AC2 (debt f9a5d1e88432): a temporary_hollowed target no-ops the frightened inflict."""
    pool = await db.get_pool()
    player_id = "cap_m13_immune"
    await seed_player(pool, player_id=player_id, location_id="accord_guild_hall")

    ctx = make_context(player_id, room=make_mock_room())
    state = None
    try:
        await combat_init._start_combat_impl(ctx, _ENCOUNTER, "The Hollow patrol turns.")
        state = ctx.userdata.combat_state
        p = state.get_participant(player_id)
        assert p is not None
        p.conditions = conditions.apply_condition(p.conditions, "temporary_hollowed", source="hollow")
        await db_mutations.save_combat_state(state.combat_id, state.to_dict(), conn=pool)

        decls = {
            player_id: {"type": "defend"},
            _ENEMY_ID: {"type": "ability", "action": _ABILITY, "target_id": player_id},
        }
        await combat_turn._declare_phase_impl(ctx, decls)

        with patch("check_resolution.dice_roll", return_value=_d20(1)):  # nat-1 -> save FAILS
            result = await combat_turn._resolve_phase_impl(ctx)

        assert isinstance(result, str), "combat continues (minions omitted -> no player damage)"
        payload = json.loads(result)
        enemy_packet = next(p for p in payload["packets"] if p["actor_id"] == _ENEMY_ID)
        assert enemy_packet["condition_immune"] == "frightened"
        assert "condition_applied" not in enemy_packet

        live = ctx.userdata.combat_state.get_participant(player_id)
        assert live is not None
        assert conditions.has_condition(live.conditions, "frightened") is False
    finally:
        if state is not None:
            await db_mutations.delete_combat_state(state.combat_id, conn=pool)
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)
