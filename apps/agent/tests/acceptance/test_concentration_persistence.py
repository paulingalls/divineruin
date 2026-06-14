"""Capstone: M3.4 concentration persistence end-to-end against a real Postgres testcontainer.

story-002 covered the concentration state layer with mock-conn / pure-unit tests; this proves
the players.data JSONB round-trip on real PG (AC5), catching JSONB seam breaks the mocked unit
tests can't. Auto-marked `acceptance` by tests/acceptance/conftest.py. Distinct from the M3.4
cast-path capstone (story-007), which proves cast -> set/end concentration composition; this
proves bare concentration read/write.

seed_player inserts a player whose data has NO `concentration` key — so the first read
exercises the create-safe default, and the first update exercises the 1-level jsonb_set that
creates the key. This is the create seam migration 047's backfill was designed to make safe;
the backfill UPDATE itself is not exercised here (seed_player runs after migrations, so the row
is never backfilled). Each test uses a distinct player_id since the testcontainer DB is shared.
"""

from __future__ import annotations

from acceptance.seeds import seed_player

import db
import db_mutations_concentration


async def test_concentration_persistence_roundtrip_real_db(reset_db_pool: str) -> None:
    """Set/read/end a concentration spell on real PG; the {concentration} JSONB key round-trips."""
    pool = await db.get_pool()
    player_id = "cap_conc_roundtrip"
    await seed_player(pool, player_id=player_id)

    # First read with no concentration key -> create-safe default (not concentrating).
    initial = await db_mutations_concentration.read_player_concentration(player_id, conn=pool)
    assert initial == {"spell_id": None}

    # Start concentrating (first update creates the key via the 1-level jsonb_set).
    await db_mutations_concentration.update_player_concentration(player_id, "arcane_fly", conn=pool)
    assert await db_mutations_concentration.read_player_concentration(player_id, conn=pool) == {
        "spell_id": "arcane_fly"
    }

    # End concentration -> spell_id cleared to null.
    await db_mutations_concentration.update_player_concentration(player_id, None, conn=pool)
    assert await db_mutations_concentration.read_player_concentration(player_id, conn=pool) == {"spell_id": None}


async def test_concentration_replaces_prior_spell_real_db(reset_db_pool: str) -> None:
    """Writing a second spell overwrites the first — the single-concentration storage invariant."""
    pool = await db.get_pool()
    player_id = "cap_conc_replace"
    await seed_player(pool, player_id=player_id)

    await db_mutations_concentration.update_player_concentration(player_id, "arcane_fly", conn=pool)
    await db_mutations_concentration.update_player_concentration(player_id, "divine_bless", conn=pool)
    assert await db_mutations_concentration.read_player_concentration(player_id, conn=pool) == {
        "spell_id": "divine_bless"
    }
