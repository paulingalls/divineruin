"""Capstone: flickering_bonus persistence end-to-end against a real Postgres testcontainer.

story-001 (M3.5) makes the Thessyn flickering_bonus a PERSISTED field at players.data
{resonance,flickering_bonus}. The mock-conn units assert the SQL shape; this proves the JSONB
round-trip on real PG — crucially that update_player_resonance MERGES (COALESCE + ||) into the
{resonance} object rather than REPLACING it, so a persisted flickering_bonus survives a later
resonance write (the regression the merge form was introduced to prevent). Auto-marked
`acceptance` by tests/acceptance/conftest.py; distinct player_id since the testcontainer DB is
shared across the session.
"""

from __future__ import annotations

from acceptance.seeds import seed_player

import db
import db_mutations_resonance


async def test_flickering_bonus_roundtrips_and_survives_resonance_writes(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    player_id = "cap_flicker_roundtrip"
    await seed_player(pool, player_id=player_id)

    # A fresh row has no flickering_bonus key -> create-safe default 0.
    assert await db_mutations_resonance.read_player_resonance(player_id, conn=pool) == {
        "current": 0,
        "flickering_bonus": 0,
        "state": "stable",
    }

    # Persist current then the bonus; both keys coexist and the bonus shifts the derived band.
    await db_mutations_resonance.update_player_resonance(player_id, 7, conn=pool)
    await db_mutations_resonance.update_player_flickering_bonus(player_id, 1, conn=pool)
    assert await db_mutations_resonance.read_player_resonance(player_id, conn=pool) == {
        "current": 7,
        "flickering_bonus": 1,
        "state": "flickering",
    }

    # The crux: a later resonance write MERGES, so it must NOT clobber the persisted bonus.
    await db_mutations_resonance.update_player_resonance(player_id, 9, conn=pool)
    assert await db_mutations_resonance.read_player_resonance(player_id, conn=pool) == {
        "current": 9,
        "flickering_bonus": 1,  # survived the resonance write (band-shift holds: 9 -> flickering)
        "state": "flickering",
    }
