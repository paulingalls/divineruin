"""Real-DB acceptance proof for migration 044's player-resonance backfill.

Migration 044 seeds `data.resonance.current = 0` on every existing player row that
lacks the key, so the resonance path is immediately queryable on legacy players
(read defaults to 0 anyway, but the backfill makes storage consistent). The
testcontainer harness replays all migrations BEFORE any player is seeded, so 044's
UPDATE runs against an empty table there — its actual mutation is never exercised by
the other resonance tests (the story-005 capstone explicitly seeds rows post-migration
and notes it skips the backfill). This test closes that gap: it applies 044's SQL to a
hand-crafted pre-state and asserts the backfill behaviour, including the idempotency
guard (`WHERE NOT (data ? 'resonance')`). Runs under REQUIRE_DOCKER; skips clean when
Docker is down. Resolves concern ba6a841b6dcd.
"""

from __future__ import annotations

import json
from pathlib import Path

import db

_MIGRATION_044 = Path(__file__).resolve().parents[4] / "scripts" / "migrations" / "044_player_resonance.sql"


async def _insert_player(pool, player_id: str, data: dict) -> None:
    await pool.execute(
        "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
        "ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb",
        player_id,
        json.dumps(data),
    )


async def _resonance_current(pool, player_id: str):
    return await pool.fetchval("SELECT data->'resonance'->>'current' FROM players WHERE player_id = $1", player_id)


async def test_migration_044_backfills_only_resonance_less_players(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    # Pre-migration-044 states: a legacy player with no resonance key, and a player
    # that already carries a nonzero resonance (must be left untouched by the guard).
    await _insert_player(pool, "mig044_legacy", {"name": "Legacy"})
    await _insert_player(pool, "mig044_existing", {"name": "Caster", "resonance": {"current": 7}})

    assert await _resonance_current(pool, "mig044_legacy") is None  # key absent pre-backfill

    await pool.execute(_MIGRATION_044.read_text())

    # The key-absent row is backfilled to 0...
    assert await _resonance_current(pool, "mig044_legacy") == "0"
    # ...and the existing nonzero resonance is preserved (WHERE NOT (data ? 'resonance')).
    assert await _resonance_current(pool, "mig044_existing") == "7"

    # Idempotent: a second run touches nothing (every row now has the key).
    await pool.execute(_MIGRATION_044.read_text())
    assert await _resonance_current(pool, "mig044_legacy") == "0"
    assert await _resonance_current(pool, "mig044_existing") == "7"
