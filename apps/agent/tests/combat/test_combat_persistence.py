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

import os

import pytest
from _db_lifecycle import _DEFAULT_DATABASE_URL
from combat._helpers import _make_combat_state

import db
import db_mutations
from session_data import CombatParticipant, CombatState


@pytest.fixture
async def dev_db_pool():
    """Point db.get_pool() at the docker-compose dev DB (started by tests/conftest.py), then
    restore. Mirrors acceptance's reset_db_pool but for the :55432 dev DB the non-acceptance
    lane already relies on; resolves the DSN the same way _db_lifecycle does."""
    prior = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = prior or _DEFAULT_DATABASE_URL
    await db.close_all()
    try:
        yield await db.get_pool()
    finally:
        await db.close_all()
        if prior is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = prior


def _mid_combat_state(combat_id: str) -> CombatState:
    """A mid-phase CombatState built from the canonical combat fixture, then advanced into a
    state that exercises every field the round-trip must preserve: a non-default beat, populated
    phase dicts, and a fallen enemy carrying death-save counters. Reuses _make_combat_state
    (the shared two-participant builder the rest of tests/combat/ uses) so the round-trip is
    proven against the same shape as the live engine, not a parallel hand-rolled one."""
    state = _make_combat_state(player_hp=12, enemy_hp=0)
    state.combat_id = combat_id
    state.round_number = 4
    state.current_turn_index = 1
    state.beat = "resolution"
    state.pending_declarations = {"player_1": {"action": "attack", "target": "goblin_scout_1"}}
    state.reactions_available = {"player_1": True, "goblin_scout_1": False}
    # Drop the enemy: set is_fallen + death-save counters directly (the helper's enemy_fallen
    # param is not wired through, so don't rely on it).
    fallen = state.get_participant("goblin_scout_1")
    assert fallen is not None
    fallen.is_fallen = True
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
