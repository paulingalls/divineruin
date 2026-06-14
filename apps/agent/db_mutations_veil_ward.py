"""DB persistence for the M3.2 Veil Ward state (story-002).

Its own module (not db_mutations.py, at the 500-line cap) keeps the ward feature
cohesive — same call as db_mutations_resonance / ability_persistence. The ward lives in
players.data JSONB at {veil_ward,active} + {veil_ward,source} (no new table), beside
{resonance} and hp/focus/stamina. `active` (bool) is the authoritative flag the cast
path reads to halve generation; `source` is the archetype id that raised the ward,
carried for narration/HUD flavor.

read returns {active, source}; update writes both. The activation tool (story-003) calls
update on activate/dismiss; the cast path (story-004) reads `active`.

Real SQL is exercised against a testcontainer at tests/acceptance/test_veil_ward_persistence.py
(the AC4 roundtrip); these functions accept conn= for the mock-conn unit tests, mirroring
db_mutations_resonance.
"""

import asyncpg

import db

_DEFAULT_WARD = {"active": False, "source": None}


async def read_player_veil_ward(
    player_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> dict:
    """Return {"active": bool, "source": str | None} for a player's Veil Ward.

    Defaults to inactive (active False, source None) when the row is missing or the
    veil_ward key is absent/NULL. `->>'active'` returns the JSONB boolean as text
    ('true'/'false'); a present-and-true value is the only active case.
    """
    _conn = conn or await db.get_pool()
    row = await _conn.fetchrow(
        "SELECT data->'veil_ward'->>'active' AS active, data->'veil_ward'->>'source' AS source "
        "FROM players WHERE player_id = $1",
        player_id,
    )
    if row is None:
        return dict(_DEFAULT_WARD)
    return {"active": row["active"] == "true", "source": row["source"]}


async def update_player_veil_ward(
    player_id: str,
    active: bool,
    source: str | None,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    """Persist the player's Veil Ward at players.data {veil_ward,active}/{veil_ward,source}.

    Uses a 1-level {veil_ward} jsonb_set with jsonb_build_object so the write succeeds
    whether or not the veil_ward key already exists (robust for rows created after the
    migration-045 backfill) — the same 1-level discipline as db_mutations_resonance.
    """
    _conn = conn or await db.get_pool()
    await _conn.execute(
        "UPDATE players SET data = jsonb_set(data, '{veil_ward}', "
        "jsonb_build_object('active', $2::boolean, 'source', $3::text)) "
        "WHERE player_id = $1",
        player_id,
        active,
        source,
    )
