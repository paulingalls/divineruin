"""Seed without a concentration key to reach key creation. This does not execute the migration backfill on old rows."""

from __future__ import annotations

from acceptance.seeds import seed_player

import db
import db_mutations_concentration


async def test_concentration_persistence_roundtrip_real_db(reset_db_pool: str) -> None:
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
    pool = await db.get_pool()
    player_id = "cap_conc_replace"
    await seed_player(pool, player_id=player_id)

    await db_mutations_concentration.update_player_concentration(player_id, "arcane_fly", conn=pool)
    await db_mutations_concentration.update_player_concentration(player_id, "divine_bless", conn=pool)
    assert await db_mutations_concentration.read_player_concentration(player_id, conn=pool) == {
        "spell_id": "divine_bless"
    }
