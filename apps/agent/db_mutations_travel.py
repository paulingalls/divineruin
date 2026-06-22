"""DB persistence for player travel state (M4.6b, story-003).

Its own module (not db_mutations.py, already at the 500-line cap) keeps the travel feature
cohesive — same shape as db_mutations_conditions / db_mutations_concentration. The in-flight
journey lives in players.data JSONB at {travel_state} (migration 055): null when not travelling,
or a dict recording an in-flight/lost journey ({destination, mode, wrong_area}). No new table.
Written by the travel tool on arrival (cleared to null) or a lost segment (the journey dict);
the read is free via db_queries.get_player. Accepts conn= for transaction participation.
"""

import json

import asyncpg

import db


async def update_player_travel_state(
    player_id: str, travel_state: dict | None, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> None:
    """Persist players.data.travel_state: null when not travelling, or a journey dict. Accepts
    None → JSON null (cleared on arrival). A 1-level jsonb_set, written whether or not the key exists."""
    _conn = conn or await db.get_pool()
    await _conn.execute(
        "UPDATE players SET data = jsonb_set(data, '{travel_state}', $2::jsonb) WHERE player_id = $1",
        player_id,
        json.dumps(travel_state),
    )
