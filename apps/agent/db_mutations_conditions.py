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

import conditions
import db


async def read_player_conditions(
    player_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> list[dict]:
    """Return the player's persistent conditions list (or [] when the row/key is absent).

    Used by combat_end to reconcile the player's persistent + beneficial-buff conditions back to
    players.data: it unions newly-acquired persistent conditions with any already stored (so a fight
    that leaves you Exhausted doesn't clobber a pre-existing Wounded) and detects a beneficial die
    (Blessed/Inspired) consumed in combat so its stale copy is dropped. The out-of-combat check/save
    read is separate and free via db_queries.get_player (it returns the whole data dict).
    """
    _conn = conn or await db.get_pool()
    row = await _conn.fetchrow(
        "SELECT data->'conditions' AS conditions FROM players WHERE player_id = $1",
        player_id,
    )
    if row is None or row["conditions"] is None:
        return []
    stored = row["conditions"]
    parsed = json.loads(stored) if isinstance(stored, str) else stored
    # Read-boundary validation (story-005): fail loud on a corrupt stored dict (unknown type /
    # non-int stacks) here, rather than letting it reach and crash a resolver later.
    return conditions.validate_conditions(parsed)


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


async def save_many_player_conditions(
    mapping: dict[str, list[dict]],
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    """Batched ``{player_id: conditions_list}`` write — ONE round-trip for N targets (M4.8 story-007,
    replacing the N-write per-target loop). ``unnest`` zips the id/conds arrays into a values set that
    drives one ``UPDATE ... FROM`` statement, applying the same ``jsonb_set(data,'{conditions}',...)``
    discipline as ``save_player_conditions`` to every row in a single execute. No-op on an empty mapping."""
    if not mapping:
        return
    _conn = conn or await db.get_pool()
    player_ids = list(mapping.keys())
    conds_json = [json.dumps(v) for v in mapping.values()]
    await _conn.execute(
        """
        UPDATE players AS p
        SET data = jsonb_set(p.data, '{conditions}', v.conds::jsonb)
        FROM unnest($1::text[], $2::text[]) AS v(pid, conds)
        WHERE p.player_id = v.pid
        """,
        player_ids,
        conds_json,
    )


# The "drop every element whose type is in the set" contract is shared with the pure-Python SSOT
# conditions.remove_conditions (conditions.py); keep the two in sync. This server-side variant exists
# so the beneficial-die consume never read-modify-writes: it filters the LIVE row in one atomic
# statement, so a condition added concurrently (e.g. a DM-applied Poisoned) is not clobbered (M4.8
# story-013). jsonb_typeof guards the JSON-null/absent conditions case (a documented stored state) —
# jsonb_array_elements would raise "cannot extract elements from a scalar" otherwise.
_REMOVE_CONDITIONS_SQL = """
UPDATE players
SET data = jsonb_set(
    data,
    '{conditions}',
    COALESCE(
        (
            SELECT jsonb_agg(elem)
            FROM jsonb_array_elements(data->'conditions') AS elem
            WHERE NOT (elem->>'type' = ANY($2::text[]))
        ),
        '[]'::jsonb
    )
)
WHERE player_id = $1
  AND jsonb_typeof(data->'conditions') = 'array'
"""


async def remove_player_conditions(
    player_id: str,
    types: tuple[str, ...],
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    """Atomically remove every condition whose ``type`` is in ``types`` from players.data {conditions}.

    One server-side statement, no read-modify-write — so a concurrent condition write is preserved
    (M4.8 story-013, the consume-side race fix). No-op when ``types`` is empty, or when the row has no
    array conditions (the ``jsonb_typeof = 'array'`` guard tolerates a JSON-null/absent key)."""
    if not types:
        return
    _conn = conn or await db.get_pool()
    await _conn.execute(_REMOVE_CONDITIONS_SQL, player_id, list(types))
