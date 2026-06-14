"""Player session counter — increment players.data{session_count} once per fresh session (M3.5).

Companions already track a session_count (companion_relationships table); players did not. The
Thessyn "Deep Adaptation" flickering bonus gates on the player having played 10+ sessions
(game_mechanics_magic.md §270-276), so M3.5 needs a per-player counter. It lives in players.data
JSONB at the top-level {session_count} key (beside {resonance}), not in a new table — the same
"state in players.data" discipline as Resonance (db_mutations_resonance.py).

hydrate_player_session is called once per FRESH session by the agent session-init (story-004) —
reconnects reuse the in-memory state and do NOT call it, mirroring
companion_relationship_queries.hydrate_companion_state, so the count advances exactly once per
session. story-003 consumes the returned count to gate the flickering bonus.

The increment is a single atomic UPDATE...RETURNING (the bump_companion_affinity discipline,
db_mutations.py): read-increment-write in one statement, so two concurrent session-inits cannot
lose an increment, and an unmatched player_id returns no row — letting us fail loud rather than
silently persist a phantom count.
"""

import asyncpg

import db


async def hydrate_player_session(
    player_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> int:
    """Increment players.data{session_count} for a FRESH session and return the new count.

    Atomic UPDATE...RETURNING: the current count (default 0 when the key is absent) is read,
    incremented by 1, persisted, and returned in one statement — race-safe and fail-loud.

    Fails loud (ValueError) on a missing player row — never silently returns 0/1.
    """
    _conn = conn or await db.get_pool()
    # jsonb_set on the 1-level '{session_count}' path works whether or not the key pre-exists;
    # COALESCE defaults an absent/NULL count to 0 before the +1. RETURNING hands back the new
    # value, and a player_id that matches no row yields no row -> fail loud below.
    row = await _conn.fetchrow(
        "UPDATE players SET data = jsonb_set(data, '{session_count}', "
        "to_jsonb(COALESCE((data->>'session_count')::int, 0) + 1)) "
        "WHERE player_id = $1 "
        "RETURNING (data->>'session_count')::int AS session_count",
        player_id,
    )
    if row is None:
        raise ValueError(f"Unknown player: {player_id!r}")
    return int(row["session_count"])
