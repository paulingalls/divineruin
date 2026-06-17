"""Combat-state read/rehydrate round-trip against the real dev Postgres (story-002, M4.1).

story-001 shipped the WRITE side: CombatState.to_dict() (asdict) serializes the phase fields
(beat/pending_declarations/reactions_available) and save_combat_state stores the whole dict as a
single JSONB column in combat_instances. This proves the missing READ side end-to-end —
load_combat_state -> CombatState.from_dict reconstructs an equal CombatState (participants as
CombatParticipant instances, phase fields + death-save counters preserved) from that stored row.

Real-PG (the docker-compose dev DB at :55432, brought up by tests/conftest.py's session hook). No
testcontainer/reset_db_pool needed — combat_instances has no FK, so a pool against the dev DB + a
unique combat_id is enough; the row is cleaned up via delete_combat_state in a finally. The
dev_db_pool fixture mirrors acceptance's reset_db_pool (point db.get_pool() at a DB, restore after)
but targets the docker-compose dev DB rather than a per-run testcontainer.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _damage_resolver, _make_combat_state

import combat_turn
import db_mutations
from session_data import CombatParticipant, CombatState, SessionData

# dev_db_pool is provided by tests/combat/conftest.py (shared with the tx-integrity suite).


def test_make_combat_state_enemy_fallen_param_sets_is_fallen() -> None:
    """The enemy_fallen builder param drops the enemy at construction (mirrors player_fallen),
    so fixtures no longer hand-set is_fallen on the goblin. Pure unit test, no DB."""
    enemy = _make_combat_state(enemy_fallen=True).get_participant("goblin_scout_1")
    assert enemy is not None and enemy.is_fallen is True
    # Default leaves the enemy standing.
    standing = _make_combat_state().get_participant("goblin_scout_1")
    assert standing is not None and standing.is_fallen is False


def test_enhancers_field_roundtrips_and_defaults_empty() -> None:
    """story-004: a participant's enhancers list survives the asdict/from_dict JSONB
    round-trip, and a row written before the field existed rehydrates to []. Pure, no DB."""
    state = _make_combat_state()
    player = state.get_participant("player_1")
    assert player is not None
    player.enhancers = ["extra_attack", "cunning_action"]

    rehydrated = CombatState.from_dict(state.to_dict())
    rp = rehydrated.get_participant("player_1")
    assert rp is not None
    assert rp.enhancers == ["extra_attack", "cunning_action"]

    # Backward compat: a participant dict missing 'enhancers' falls back to the empty default.
    legacy = state.to_dict()
    for p in legacy["participants"]:
        p.pop("enhancers", None)
    legacy_state = CombatState.from_dict(legacy)
    assert all(p.enhancers == [] for p in legacy_state.participants)


def _mid_combat_state(combat_id: str) -> CombatState:
    """A mid-phase CombatState built from the canonical combat fixture, then advanced into a
    state that exercises every field the round-trip must preserve: a non-default beat, populated
    phase dicts, and a fallen enemy carrying death-save counters. Reuses _make_combat_state
    (the shared two-participant builder the rest of tests/combat/ uses) so the round-trip is
    proven against the same shape as the live engine, not a parallel hand-rolled one."""
    state = _make_combat_state(player_hp=12, enemy_hp=0, enemy_fallen=True)
    state.combat_id = combat_id
    state.round_number = 4
    state.current_turn_index = 1
    state.beat = "resolution"
    state.pending_declarations = {"player_1": {"action": "attack", "target": "goblin_scout_1"}}
    state.reactions_available = {"player_1": True, "goblin_scout_1": False}
    state.ac_modifiers = {"player_1": 2}  # a Defend stance in flight (M4.2, story-002)
    # is_fallen now comes from the enemy_fallen param; death-save counters aren't part of the
    # builder, so set those directly to exercise the round-trip.
    fallen = state.get_participant("goblin_scout_1")
    assert fallen is not None
    fallen.death_save_successes = 2
    fallen.death_save_failures = 1
    return state


async def test_load_combat_state_roundtrips_mid_phase_state(dev_db_pool) -> None:
    pool = dev_db_pool
    combat_id = "combat_persist_roundtrip_story002"
    original = _mid_combat_state(combat_id)

    try:
        await db_mutations.save_combat_state(combat_id, original.to_dict(), conn=pool)
        loaded = await db_mutations.load_combat_state(combat_id, conn=pool)

        assert loaded is not None
        # Participants come back as CombatParticipant instances, not raw dicts.
        assert all(isinstance(p, CombatParticipant) for p in loaded.participants)
        # Phase fields + death-save counters survive the JSONB round-trip.
        assert loaded.beat == "resolution"
        assert loaded.pending_declarations == original.pending_declarations
        assert loaded.reactions_available == original.reactions_available
        assert loaded.ac_modifiers == {"player_1": 2}
        fallen = loaded.get_participant("goblin_scout_1")
        assert fallen is not None
        assert fallen.is_fallen is True
        assert fallen.death_save_successes == 2
        assert fallen.death_save_failures == 1
        # Whole-state deep equality via the asdict shape (inverse of from_dict).
        assert loaded.to_dict() == original.to_dict()
    finally:
        await db_mutations.delete_combat_state(combat_id, conn=pool)


async def test_load_combat_state_returns_none_for_unknown_id(dev_db_pool) -> None:
    assert await db_mutations.load_combat_state("combat_does_not_exist_story002", conn=dev_db_pool) is None


def _rollback_resolution_state(combat_id: str, player_id: str, enemy_id: str) -> CombatState:
    """A RESOLUTION-beat state with unique participant ids (dev DB is shared across the -n8
    fast lane, so player_id must not collide). Enemy declares an attack on the player so
    resolve_phase writes update_player_hp(player_id) inside the phase transaction."""
    return CombatState(
        combat_id=combat_id,
        participants=[
            CombatParticipant(
                id=player_id,
                name="Kael",
                type="player",
                initiative=15,
                hp_current=25,
                hp_max=25,
                ac=14,
                action_pool=[{"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}],
            ),
            CombatParticipant(
                id=enemy_id,
                name="Goblin",
                type="enemy",
                initiative=12,
                hp_current=7,
                hp_max=7,
                ac=13,
                action_pool=[{"name": "Scimitar", "damage": "1d6", "damage_type": "slashing"}],
                xp_value=50,
            ),
        ],
        initiative_order=[player_id, enemy_id],
        beat="resolution",
        pending_declarations={
            player_id: {"type": "attack", "action": "Longsword", "target_id": enemy_id},
            enemy_id: {"type": "attack", "action": "Scimitar", "target_id": player_id},
        },
    )


async def test_resolve_phase_rolls_back_player_hp_when_save_combat_state_fails(dev_db_pool, monkeypatch) -> None:
    """A mid-phase DB failure must NOT leave players.data diverged from the combat_instances SSOT
    (debt 084c7d0bc457). The enemy packet writes update_player_hp inside the phase transaction; when
    the trailing save_combat_state raises, the whole phase rolls back and the player's persisted HP
    is unchanged. Without the transaction the per-packet HP write commits independently and diverges."""
    pool = dev_db_pool
    player_id = "cap_s010_rollback_player"
    combat_id = "combat_s010_rollback"

    # Seed a real player row at HP 25 (update_player_hp jsonb_set needs data.hp to exist).
    await pool.execute(
        "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
        "ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb",
        player_id,
        json.dumps({"player_id": player_id, "hp": {"current": 25, "max": 25}}),
    )

    # Real db_mutations except save_combat_state, which raises after the per-packet HP write.
    monkeypatch.setattr(db_mutations, "save_combat_state", AsyncMock(side_effect=RuntimeError("boom")))
    queries = MagicMock()
    queries.get_player_inventory = AsyncMock(return_value=[])  # no equipped items -> no durability writes
    break_mod = MagicMock()
    break_mod.break_concentration_on_damage = AsyncMock(return_value=None)

    ctx = MagicMock()
    ctx.userdata = SessionData(player_id=player_id, location_id="accord_guild_hall", room=None)
    pre_phase_state = _rollback_resolution_state(combat_id, player_id, "cap_s010_enemy")
    ctx.userdata.combat_state = pre_phase_state

    try:
        with pytest.raises(RuntimeError, match="boom"):
            await combat_turn._resolve_phase_impl(
                ctx, queries=queries, resolver=_damage_resolver(3), concentration_break_mod=break_mod
            )
        # The enemy's 3-damage hit (25 -> 22) was rolled back with the failed save: HP is still 25.
        row = await pool.fetchrow(
            "SELECT (data->'hp'->>'current')::int AS hp FROM players WHERE player_id = $1", player_id
        )
        assert row["hp"] == 25

        # In-memory state must NOT diverge from the rolled-back DB SSOT: session.combat_state is
        # still the pristine pre-phase object (the engine deep-copies, and the post-commit
        # session.combat_state assignment is skipped on rollback), with the player at HP 25 — so a
        # retried turn proceeds from committed state, not the discarded mid-phase HP 22.
        assert ctx.userdata.combat_state is pre_phase_state
        player_part = next(p for p in ctx.userdata.combat_state.participants if p.id == player_id)
        assert player_part.hp_current == 25
    finally:
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)
        await db_mutations.delete_combat_state(combat_id, conn=pool)
