"""DB persistence for cross-encounter status conditions (M4.3, story-004).

Its own module (not db_mutations.py, at the 500-line cap) keeps the conditions feature cohesive —
same shape as db_mutations_concentration / db_mutations_resonance / db_mutations_veil_ward.
Persistent conditions (Wounded/Exhausted/Hollowed — those whose catalog spec marks
persists_across_encounters) live in players.data JSONB at {conditions}: a list of condition dicts
({type, duration, source, stacks?, stage?}), beside {resonance}, {veil_ward}, {concentration}. No
new table — see decision persistent-conditions-jsonb (player-scoped, whole-set reads, frequent
mutation = the JSONB sweet spot).

This is the WRITE side, called by combat_end when a fight ends. The READ is free: db_queries.get_player
already returns the whole players.data dict (incl. conditions), and the resolvers default to [] when
the key is absent (story-003) — so out-of-combat checks/saves see persistent conditions with no
extra fetch. In-combat conditions are NOT written here; they ride combat_instances.data via
save_combat_state. Accepts conn= for transaction participation, mirroring db_mutations_concentration.
"""

import json

import asyncpg

import db


async def read_player_conditions(
    player_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> list[dict]:
    """Return the player's persistent conditions list (or [] when the row/key is absent).

    Used by combat_end to MERGE newly-acquired persistent conditions with any already stored — so a
    fight that leaves you Exhausted doesn't clobber a pre-existing Wounded (combat-START load is
    deferred, so the participant doesn't carry the prior store in). The out-of-combat check/save read
    is separate and free via db_queries.get_player (it returns the whole data dict).
    """
    _conn = conn or await db.get_pool()
    row = await _conn.fetchrow(
        "SELECT data->'conditions' AS conditions FROM players WHERE player_id = $1",
        player_id,
    )
    if row is None or row["conditions"] is None:
        return []
    stored = row["conditions"]
    return json.loads(stored) if isinstance(stored, str) else stored


async def save_player_conditions(
    player_id: str,
    conditions: list[dict],
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    """Persist the full conditions list at players.data {conditions} (a 1-level jsonb_set, the same
    discipline as the sibling mutation modules — writes whether or not the key already exists). The
    full list is authoritative: an empty list clears the store."""
    _conn = conn or await db.get_pool()
    await _conn.execute(
        "UPDATE players SET data = jsonb_set(data, '{conditions}', $2::jsonb) WHERE player_id = $1",
        player_id,
        json.dumps(conditions),
    )
