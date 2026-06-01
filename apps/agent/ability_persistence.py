"""DB persistence for the M2.2 ability system.

Holds the read + writes for ability activation and elective management. Lives in
its own module (not db_queries/db_mutations) because db_mutations.py is at the
500-line cap; grouping the ability-system persistence keeps the feature cohesive
and every file under its limit (decision ability-persistence-module).

- update_player_resources: deduct Stamina/Focus after an ability is activated.
- set_elective_equipped / get_character_abilities: the character_abilities table
  (migration 030) — which L4/L8 electives a character currently has equipped.
"""

import json

import asyncpg

import db


async def update_player_resources(
    player_id: str,
    *,
    stamina: int | None = None,
    focus: int | None = None,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    """Set the player's current Stamina and/or Focus pool(s).

    Only the pools passed (non-None) are written, so an ability that costs only
    stamina never blind-writes a `{focus,current}` key the player may not have.
    A no-op when both are None.
    """
    if stamina is None and focus is None:
        return
    _conn = conn or await db.get_pool()
    expr = "data"
    params: list[object] = [player_id]
    if stamina is not None:
        params.append(json.dumps(stamina))
        expr = f"jsonb_set({expr}, '{{stamina,current}}', ${len(params)}::jsonb)"
    if focus is not None:
        params.append(json.dumps(focus))
        expr = f"jsonb_set({expr}, '{{focus,current}}', ${len(params)}::jsonb)"
    await _conn.execute(f"UPDATE players SET data = {expr} WHERE player_id = $1", *params)


async def set_elective_equipped(
    player_id: str,
    ability_id: str,
    equipped: bool,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    """Upsert a character_abilities row's equipped flag.

    Symmetric for both directions of an elective swap: the swapped-out technique is
    set equipped=FALSE (its row is kept, so it stays re-selectable) and the chosen
    option is set equipped=TRUE (inserted if the character never held it before).
    """
    _conn = conn or await db.get_pool()
    await _conn.execute(
        """
        INSERT INTO character_abilities (player_id, ability_id, equipped)
        VALUES ($1, $2, $3)
        ON CONFLICT (player_id, ability_id) DO UPDATE SET equipped = $3
        """,
        player_id,
        ability_id,
        equipped,
    )


async def get_character_abilities(
    player_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> list[dict]:
    """Return the character's known abilities as {ability_id, equipped} rows."""
    _conn = conn or await db.get_pool()
    rows = await _conn.fetch(
        "SELECT ability_id, equipped FROM character_abilities WHERE player_id = $1",
        player_id,
    )
    return [{"ability_id": r["ability_id"], "equipped": r["equipped"]} for r in rows]
