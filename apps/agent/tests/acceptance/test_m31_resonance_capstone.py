"""Seed after migrations to exercise key creation; this does not certify the backfill UPDATE."""

from __future__ import annotations

from acceptance.seeds import seed_player

import db
import db_mutations_resonance
import resonance

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
    arcane = resonance.calculate_resonance_generated(focus_cost=10, source="arcane", terrain=None)
    assert arcane == 6
    await db_mutations_resonance.update_player_resonance(player_id, arcane, conn=pool)
    assert await db_mutations_resonance.read_player_resonance(player_id, conn=pool) == {
        "current": 6,
        "flickering_bonus": 0,
        "state": "flickering",
    }

    # primal in city: ceil(10 * 0.5) = 5 -> flickering
    primal = resonance.calculate_resonance_generated(focus_cost=10, source="primal", terrain="city")
    assert primal == 5
    await db_mutations_resonance.update_player_resonance(player_id, primal, conn=pool)
    assert await db_mutations_resonance.read_player_resonance(player_id, conn=pool) == {
        "current": 5,
        "flickering_bonus": 0,
        "state": "flickering",
    }
