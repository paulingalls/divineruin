"""DB persistence for the M2.2 ability system.

Holds the read + writes for ability activation and elective management. Lives in
its own module (not db_queries/db_mutations) because db_mutations.py is at the
500-line cap; grouping the ability-system persistence keeps the feature cohesive
and every file under its limit (decision ability-persistence-module).

- update_player_resources: deduct Stamina/Focus after an ability is activated.
- set_elective_equipped / get_character_abilities: the character_abilities table
  (migration 030) — which L4/L8 electives a character currently has equipped.
- set_active_variant / get_active_variant: the character_active_variants table
  (migration 038) — which unlocked mentor variant currently overrides a base
  technique (one per technique; M9 story-003).
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


async def set_active_variant(
    player_id: str,
    ability_id: str,
    variant_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    """Make a mentor variant the active override on its base technique (migration 038).

    The PK (player_id, ability_id) + ON CONFLICT DO UPDATE enforces one active variant per
    technique: training a second variant for the same base ability REPLACES the active one
    (swap requires re-training). Callers pass a variant already validated against the ability
    (mentor_variants.get_variant fails loud on a mismatch).
    """
    _conn = conn or await db.get_pool()
    await _conn.execute(
        """
        INSERT INTO character_active_variants (player_id, ability_id, variant_id)
        VALUES ($1, $2, $3)
        ON CONFLICT (player_id, ability_id) DO UPDATE SET variant_id = $3
        """,
        player_id,
        ability_id,
        variant_id,
    )


async def get_active_variant(
    player_id: str,
    ability_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> str | None:
    """Return the active variant id overriding a base technique, or None when none is active."""
    _conn = conn or await db.get_pool()
    return await _conn.fetchval(
        "SELECT variant_id FROM character_active_variants WHERE player_id = $1 AND ability_id = $2",
        player_id,
        ability_id,
    )


async def owns_elective(
    player_id: str,
    ability_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> bool:
    """Whether the player owns a given elective technique (story-006).

    Ownership is "has a character_abilities row", NOT "currently equipped": a
    swapped-out elective keeps its row (set_elective_equipped sets equipped=FALSE
    but never deletes), so it stays owned. Core/reaction abilities have no row and
    are handled by abilities.owns_ability without touching this query.
    """
    _conn = conn or await db.get_pool()
    # EXISTS always yields a non-null boolean; coerce for the static type checker.
    return bool(
        await _conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM character_abilities WHERE player_id = $1 AND ability_id = $2)",
            player_id,
            ability_id,
        )
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
