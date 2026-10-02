"""Condition resolution on Postgres with a test-authored catalog action."""

from __future__ import annotations

import json
from copy import deepcopy
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _resolve_round
from acceptance._catalog_cutover_helpers import cold_catalog_reads as cold_catalog_reads
from acceptance.seeds import seed_player
from sample_fixtures import make_context, make_mock_room

import combat_init
import combat_turn
import conditions
import db
import db_mutations

_ENCOUNTER = "hollow_patrol_greyvale"
_ENEMY_ID = "mawling_1"
_ACTION = "Test Shriek"


@pytest.fixture(autouse=True)
async def test_authored_condition_catalog(reset_db_pool):
    from creature_catalog import query_creature_by_id

    pool = await db.get_pool()
    original = await query_creature_by_id("hollow_mawling")
    row = deepcopy(original)
    row["attacks"].append(
        {
            **row["attacks"][0],
            "name": _ACTION,
            "damage": "0",
            "damage_type": "none",
            "applies_condition": "frightened",
            "save": "wisdom",
            "dc": 13,
        }
    )
    await pool.execute("UPDATE creatures SET data = $2::jsonb WHERE id = $1", row["id"], json.dumps(row))
    try:
        yield
    finally:
        await pool.execute("UPDATE creatures SET data = $2::jsonb WHERE id = $1", original["id"], json.dumps(original))


async def _start_and_declare(ctx, player_id: str) -> None:
    await combat_init._start_combat_impl(ctx, _ENCOUNTER, "The Hollow patrol turns.")
    decls = {
        player_id: {"type": "defend"},
        _ENEMY_ID: {"type": "attack", "action": _ACTION, "target_id": player_id},
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
            result = await _resolve_round(ctx)

        assert not isinstance(result, tuple), "combat continues (minions omitted -> no player damage)"
        payload = result
        enemy_packet = next(p for p in payload["packets"] if p["actor_id"] == _ENEMY_ID)
        assert enemy_packet["condition_inflicted"] == "frightened"

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
            _ENEMY_ID: {"type": "attack", "action": _ACTION, "target_id": player_id},
        }
        await combat_turn._declare_phase_impl(ctx, decls)

        with patch("check_resolution.dice_roll", return_value=_d20(1)):  # nat-1 -> save FAILS
            result = await _resolve_round(ctx)

        assert not isinstance(result, tuple), "combat continues (minions omitted -> no player damage)"
        payload = result
        enemy_packet = next(p for p in payload["packets"] if p["actor_id"] == _ENEMY_ID)
        assert enemy_packet["condition_immune"] == "frightened"
        assert "condition_inflicted" not in enemy_packet

        live = ctx.userdata.combat_state.get_participant(player_id)
        assert live is not None
        assert conditions.has_condition(live.conditions, "frightened") is False
    finally:
        if state is not None:
            await db_mutations.delete_combat_state(state.combat_id, conn=pool)
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)
