"""Capstone: M3.1 Resonance System end-to-end against a real Postgres testcontainer.

Stories 001-004 shipped the Resonance system with mock-conn / unit coverage; story-002
explicitly DEFERRED the real-DB round-trip to this capstone (ADR 0003). This test proves
the Python surfaces compose against one seeded testcontainer (auto-marked `acceptance` by
tests/acceptance/conftest.py), catching JSONB seam breaks the mocked unit tests can't:

- **message_event** (this file): the rules engine (resonance.py), the players.data JSONB
  persistence (db_mutations_resonance.py), and the session/rest/push wiring
  (session_data.py + rest_mechanics.py + resonance_events.py) composed on real PG.
  This proves the create-safe default read + 1-level jsonb_set create seam that
  migration 044's backfill was designed to make safe — NOT the backfill UPDATE itself,
  which never runs against a row seed_player inserts after migrations.
- **automation** (mobile HUD): already proven by story-004's bun suite
  (apps/mobile/src/__tests__/resonance-hud.test.ts) — not re-run in a pytest capstone.

Each test uses a distinct player_id since the testcontainer DB is shared across the
session. State is always DERIVED on read (resonance.get_resonance_state), never stored.
"""

from __future__ import annotations

from acceptance.seeds import seed_player

import db
import db_mutations_resonance
import resonance
import resonance_events
import rest_mechanics
from event_types import RESONANCE_CHANGED
from resonance_events import RESONANCE_DISPLAY_MAX
from session_data import SessionData

# (persisted current, derived state) across the spec bands: stable 0-4, flickering 5-8,
# overreach 9+ (game_mechanics_magic.md:100-106).
_BANDS = [(4, "stable"), (5, "flickering"), (8, "flickering"), (9, "overreach"), (10, "overreach")]


async def test_resonance_persistence_roundtrip_real_db(reset_db_pool: str) -> None:
    """Write/read/reset resonance on real PG; state derives correctly across every band."""
    pool = await db.get_pool()
    player_id = "cap_res_roundtrip"
    # seed_player inserts a player whose data has NO `resonance` key — so the first read
    # exercises the create-safe default, and the first update exercises the 1-level
    # jsonb_set that creates the key (story-002's decision). This is the create seam
    # migration 044's backfill was designed to make safe; the backfill UPDATE itself is
    # not exercised here (seed_player runs after migrations, so the row is never backfilled).
    await seed_player(pool, player_id=player_id)

    initial = await db_mutations_resonance.read_player_resonance(player_id, conn=pool)
    assert initial == {"current": 0, "state": "stable"}

    for current, expected_state in _BANDS:
        await db_mutations_resonance.update_player_resonance(player_id, current, conn=pool)
        got = await db_mutations_resonance.read_player_resonance(player_id, conn=pool)
        assert got == {"current": current, "state": expected_state}

    await db_mutations_resonance.reset_player_resonance(player_id, conn=pool)
    assert await db_mutations_resonance.read_player_resonance(player_id, conn=pool) == {
        "current": 0,
        "state": "stable",
    }


async def test_generated_resonance_persists_and_derives_state(reset_db_pool: str) -> None:
    """Compose rules -> persistence (the M3.3 cast preview): generate, persist, derive."""
    pool = await db.get_pool()
    player_id = "cap_res_generated"
    await seed_player(pool, player_id=player_id)

    # arcane: ceil(10 * 0.6) = 6 -> flickering
    arcane = resonance.calculate_resonance_generated(focus_cost=10, source="arcane")
    assert arcane == 6
    await db_mutations_resonance.update_player_resonance(player_id, arcane, conn=pool)
    assert await db_mutations_resonance.read_player_resonance(player_id, conn=pool) == {
        "current": 6,
        "state": "flickering",
    }

    # primal in hollow-corrupted terrain: ceil(10 * 0.8) = 8 -> flickering (band edge)
    primal = resonance.calculate_resonance_generated(focus_cost=10, source="primal", terrain="hollow_corrupted")
    assert primal == 8
    await db_mutations_resonance.update_player_resonance(player_id, primal, conn=pool)
    assert await db_mutations_resonance.read_player_resonance(player_id, conn=pool) == {
        "current": 8,
        "state": "flickering",
    }


async def test_rest_path_resets_and_persists_real_db(reset_db_pool: str) -> None:
    """story-003 rest path on real PG: the session reset zeroes memory AND persists."""
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
        "state": "stable",
    }


async def test_rest_reset_then_publish_emits_resonance_changed_event(reset_db_pool: str) -> None:
    """Full chain: rest reset (persisted) -> publish RESONANCE_CHANGED to the event bus."""
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
    assert resonance_events_published[0].payload == {
        "state": "stable",
        "current": 0,
        "max": RESONANCE_DISPLAY_MAX,
    }
