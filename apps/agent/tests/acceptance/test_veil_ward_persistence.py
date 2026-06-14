"""Capstone: M3.2 Veil Ward persistence end-to-end against a real Postgres testcontainer.

story-002 covered the ward state layer with mock-conn / pure-unit tests; this proves the
players.data JSONB round-trip on real PG (AC4), catching JSONB seam breaks the mocked unit
tests can't. Auto-marked `acceptance` by tests/acceptance/conftest.py. Distinct from the
M3.2 cast-path capstone (story-006), which proves the cast -> echo -> halving composition;
this proves bare ward read/write.

seed_player inserts a player whose data has NO `veil_ward` key — so the first read
exercises the create-safe default, and the first update exercises the 1-level jsonb_set
that creates the key. This is the create seam migration 045's backfill was designed to make
safe; the backfill UPDATE itself is not exercised here (seed_player runs after migrations,
so the row is never backfilled). Each test uses a distinct player_id since the testcontainer
DB is shared across the session.
"""

from __future__ import annotations

from acceptance.seeds import seed_player

import db
import db_mutations_veil_ward


async def test_veil_ward_persistence_roundtrip_real_db(reset_db_pool: str) -> None:
    """Write/read/dismiss a Veil Ward on real PG; the {veil_ward} JSONB key round-trips."""
    pool = await db.get_pool()
    player_id = "cap_ward_roundtrip"
    await seed_player(pool, player_id=player_id)

    # First read with no veil_ward key -> create-safe default (inactive).
    initial = await db_mutations_veil_ward.read_player_veil_ward(player_id, conn=pool)
    assert initial == {"active": False, "source": None}

    # Activate (first update creates the key via the 1-level jsonb_set).
    await db_mutations_veil_ward.update_player_veil_ward(player_id, True, "cleric", conn=pool)
    assert await db_mutations_veil_ward.read_player_veil_ward(player_id, conn=pool) == {
        "active": True,
        "source": "cleric",
    }

    # Dismiss -> inactive, source cleared.
    await db_mutations_veil_ward.update_player_veil_ward(player_id, False, None, conn=pool)
    assert await db_mutations_veil_ward.read_player_veil_ward(player_id, conn=pool) == {
        "active": False,
        "source": None,
    }


async def test_veil_ward_source_survives_roundtrip_per_archetype(reset_db_pool: str) -> None:
    """Each ward source archetype id round-trips through the JSONB column unchanged."""
    pool = await db.get_pool()
    player_id = "cap_ward_sources"
    await seed_player(pool, player_id=player_id)

    for source in ("cleric", "druid", "paladin"):
        await db_mutations_veil_ward.update_player_veil_ward(player_id, True, source, conn=pool)
        assert await db_mutations_veil_ward.read_player_veil_ward(player_id, conn=pool) == {
            "active": True,
            "source": source,
        }
