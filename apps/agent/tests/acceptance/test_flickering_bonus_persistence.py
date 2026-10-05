"""A resonance update must merge rather than replace its object or it would erase flickering_bonus."""

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
