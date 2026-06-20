"""DB persistence for the M4.4 permanent death history (story-001).

Its own module (not db_mutations.py, at the 500-line cap) keeps the death feature cohesive — same
shape as db_mutations_conditions / db_mutations_veil_ward / db_mutations_resonance. The history lives
in players.data JSONB at {death_history}: {"count": int, "costs": [<DeathCost dict>, ...]}, beside
{conditions}, {resonance}, {veil_ward} (decision death-system-module-layout — player-scoped, whole-set
reads, infrequent mutation = the JSONB fit; no new table).

The count is permanent and never resets (the spec's death_counter). record_death takes an
already-computed DeathCost whose death_count is authoritative, so it does not self-increment — the
caller (story-003 resurrection) does `read.count + 1 -> determine_death_cost -> record_death`. Accepts
conn= for transaction participation, mirroring the sibling mutation modules.
"""

import json
from dataclasses import asdict

import asyncpg

import db
from death_cost import DeathCost


async def read_death_history(
    player_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> dict:
    """Return the player's death history (or {"count": 0, "costs": []} when the row/key is absent)."""
    _conn = conn or await db.get_pool()
    row = await _conn.fetchrow(
        "SELECT data->'death_history' AS death_history FROM players WHERE player_id = $1",
        player_id,
    )
    if row is None or row["death_history"] is None:
        return {"count": 0, "costs": []}
    stored = row["death_history"]
    return json.loads(stored) if isinstance(stored, str) else stored


async def record_death(
    player_id: str,
    cost: DeathCost,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> dict:
    """Append ``cost`` to the player's death ledger and advance the count to ``cost.death_count``.

    The full death_history is authoritative and written via a 1-level jsonb_set (the same discipline
    as save_player_conditions — works whether or not the key pre-exists). Returns the new history dict.
    """
    _conn = conn or await db.get_pool()
    history = await read_death_history(player_id, conn=_conn)
    updated = {
        "count": cost.death_count,  # authoritative — no double-increment
        "costs": [*history["costs"], asdict(cost)],
    }
    await _conn.execute(
        "UPDATE players SET data = jsonb_set(data, '{death_history}', $2::jsonb) WHERE player_id = $1",
        player_id,
        json.dumps(updated),
    )
    return updated
