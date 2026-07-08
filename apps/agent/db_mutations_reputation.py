"""DB persistence for player faction reputation (story-002, M23).

Its own module (db_mutations.py sits at the 500-line cap) keeps the reputation writer
cohesive — same call as db_mutations_veil_ward / db_mutations_resonance. Standing lives in
the player_reputation table (player_id, faction_id, data JSONB) at data["value"] (int) —
the exact shape db_queries.get_player_faction_reputation already reads (that reader
forward-defined the shape with "no writer ships yet"; this is the writer).

Mirrors set_npc_disposition's INSERT ... ON CONFLICT upsert, but ADDITIVE: the delta (from
reputation.reputation_shift) accrues onto the existing value in ONE atomic statement, so
concurrent shifts don't lose updates (no read-then-write race). Callers accept conn= to
join a FOR UPDATE-locked outer transaction (e.g. the quest tool's stage-advance tx).
"""

import asyncpg

import db


async def adjust_player_faction_reputation(
    player_id: str,
    faction_id: str,
    delta: int,
    reason: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> int:
    """Add `delta` to the player's reputation with `faction_id`; return the new value.

    Atomic upsert on player_reputation (PK player_id, faction_id): a missing row starts at
    `delta`; an existing row accrues `delta` onto its stored value in the same statement,
    COALESCE-guarded so a legacy row without a value key starts from 0. `reason` is stored
    for audit/narration (the stance reader only consumes value). One statement = no
    read-then-write race under concurrent shifts.
    """
    _conn = conn or await db.get_pool()
    new_value = await _conn.fetchval(
        """
        INSERT INTO player_reputation (player_id, faction_id, data)
        VALUES ($1, $2, jsonb_build_object('value', $3::int, 'reason', $4::text))
        ON CONFLICT (player_id, faction_id)
        DO UPDATE SET data = jsonb_build_object(
            'value', COALESCE((player_reputation.data->>'value')::int, 0) + $3::int,
            'reason', $4::text)
        RETURNING (data->>'value')::int
        """,
        player_id,
        faction_id,
        delta,
        reason,
    )
    # INSERT ... ON CONFLICT DO UPDATE ... RETURNING always affects a row; a None here would
    # mean the statement matched nothing, which is impossible — fail loud rather than mask it.
    if new_value is None:
        raise RuntimeError(f"reputation upsert returned no row for {player_id}/{faction_id}")
    return new_value
