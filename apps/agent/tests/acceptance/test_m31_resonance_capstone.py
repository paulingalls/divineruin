"""Seed after migrations to exercise key creation; this does not certify the backfill UPDATE."""

from __future__ import annotations

from acceptance.seeds import seed_player

import db
import db_mutations_resonance
import resonance
import resonance_events
import rest_mechanics
from event_types import RESONANCE_CHANGED
from session_data import SessionData

# (persisted current, derived state) across the spec bands: stable 0-4, flickering 5-8,
# overreach 9+ (game_mechanics_magic.md:100-106).
_BANDS = [(4, "stable"), (5, "flickering"), (8, "flickering"), (9, "overreach"), (10, "overreach")]


async def test_resonance_persistence_roundtrip_real_db(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    player_id = "cap_res_roundtrip"
    # seed_player inserts a player whose data has NO `resonance` key — so the first read
    # exercises the create-safe default, and the first update exercises the 1-level
    # jsonb_set that creates the key (story-002's decision). This is the create seam
    # migration 044's backfill was designed to make safe; the backfill UPDATE itself is
    # not exercised here (seed_player runs after migrations, so the row is never backfilled).
    await seed_player(pool, player_id=player_id)

    initial = await db_mutations_resonance.read_player_resonance(player_id, conn=pool)
    assert initial == {"current": 0, "flickering_bonus": 0, "state": "stable"}

    for current, expected_state in _BANDS:
        await db_mutations_resonance.update_player_resonance(player_id, current, conn=pool)
        got = await db_mutations_resonance.read_player_resonance(player_id, conn=pool)
        assert got == {"current": current, "flickering_bonus": 0, "state": expected_state}

    await db_mutations_resonance.reset_player_resonance(player_id, conn=pool)
    assert await db_mutations_resonance.read_player_resonance(player_id, conn=pool) == {
        "current": 0,
        "flickering_bonus": 0,
        "state": "stable",
    }


async def test_generated_resonance_persists_and_derives_state(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    player_id = "cap_res_generated"
    await seed_player(pool, player_id=player_id)

    # arcane: ceil(10 * 0.6) = 6 -> flickering
    arcane = resonance.calculate_resonance_generated(focus_cost=10, source="arcane")
    assert arcane == 6
    await db_mutations_resonance.update_player_resonance(player_id, arcane, conn=pool)
    assert await db_mutations_resonance.read_player_resonance(player_id, conn=pool) == {
        "current": 6,
        "flickering_bonus": 0,
        "state": "flickering",
    }

    # primal in hollow-corrupted terrain: ceil(10 * 0.8) = 8 -> flickering (band edge)
    primal = resonance.calculate_resonance_generated(focus_cost=10, source="primal", terrain="hollow_corrupted")
    assert primal == 8
    await db_mutations_resonance.update_player_resonance(player_id, primal, conn=pool)
    assert await db_mutations_resonance.read_player_resonance(player_id, conn=pool) == {
        "current": 8,
        "flickering_bonus": 0,
        "state": "flickering",
    }


async def test_rest_path_resets_and_persists_real_db(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    player_id = "cap_res_rest"
    await seed_player(pool, player_id=player_id)
    # Persist a nonzero (flickering) baseline so the reset is observable.
    await db_mutations_resonance.update_player_resonance(player_id, 7, conn=pool)

    session = SessionData(player_id=player_id, location_id="accord_guild_hall", room=None)
    session.resonance.current = 7
    assert session.resonance.state == "flickering"

    await rest_mechanics.reset_resonance_on_rest(session, conn=pool)

    # In-memory zeroed...
    assert session.resonance.current == 0
    assert session.resonance.state == "stable"
    # ...and persisted to real PG.
    assert await db_mutations_resonance.read_player_resonance(player_id, conn=pool) == {
        "current": 0,
        "flickering_bonus": 0,
        "state": "stable",
    }


async def test_rest_reset_then_publish_emits_resonance_changed_event(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    player_id = "cap_res_publish"
    await seed_player(pool, player_id=player_id)
    await db_mutations_resonance.update_player_resonance(player_id, 7, conn=pool)

    session = SessionData(player_id=player_id, location_id="accord_guild_hall", room=None)
    session.resonance.current = 7

    await rest_mechanics.reset_resonance_on_rest(session, conn=pool)
    # room is None, so the push lands on the in-process event bus only.
    await resonance_events.publish_resonance_changed(session)

    events = session.event_bus.drain()
    resonance_events_published = [e for e in events if e.event_type == RESONANCE_CHANGED]
    assert len(resonance_events_published) == 1
    # No-number spec (magic.md:98): the wire carries the qualitative state only,
    # plus the caster_id discriminator (M14 story-004) for multi-player HUD routing.
    assert resonance_events_published[0].payload == {"caster_id": player_id, "state": "stable"}
