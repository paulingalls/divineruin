"""Database read queries -- player state, NPC state, inventory, skills, quests, session.

All async, accept optional conn parameter.
"""

import asyncio
import json
import logging

import asyncpg

import db
import db_activity_queries
import db_content_queries

logger = logging.getLogger("divineruin.db")


# --- State queries (not cached) ---


async def get_npc_disposition(
    npc_id: str,
    player_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
    for_update: bool = False,
) -> str | None:
    _conn = conn or await db.get_pool()
    sql = "SELECT data FROM npc_dispositions WHERE npc_id = $1 AND player_id = $2"
    if for_update:
        sql += " FOR UPDATE"
    row = await _conn.fetchrow(sql, npc_id, player_id)
    if row is None:
        return None
    data = json.loads(row["data"])
    return data.get("disposition")


async def get_npc_dispositions(
    npc_ids: list[str], player_id: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> dict[str, str]:
    """Batch-fetch dispositions for multiple NPCs. Returns {npc_id: disposition}."""
    if not npc_ids:
        return {}
    _conn = conn or await db.get_pool()
    rows = await _conn.fetch(
        "SELECT npc_id, data FROM npc_dispositions WHERE npc_id = ANY($1) AND player_id = $2",
        npc_ids,
        player_id,
    )
    return {row["npc_id"]: json.loads(row["data"]).get("disposition", "neutral") for row in rows}


async def get_player(
    player_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
    for_update: bool = False,
) -> dict | None:
    _conn = conn or await db.get_pool()
    sql = "SELECT data FROM players WHERE player_id = $1"
    if for_update:
        sql += " FOR UPDATE"
    row = await _conn.fetchrow(sql, player_id)
    if row is None:
        return None
    data = json.loads(row["data"])
    # Guard against double-encoded JSONB (stored as JSON string instead of object)
    if isinstance(data, str):
        logger.warning("Double-encoded player data for %s -- run data migration", player_id)
        data = json.loads(data)
    if not isinstance(data, dict):
        logger.warning("Player %s has non-dict data: %s", player_id, type(data).__name__)
        return None
    return data


async def get_npc_combat_stats(npc_id: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None) -> dict | None:
    _conn = conn or await db.get_pool()
    row = await _conn.fetchrow("SELECT data FROM npc_state WHERE npc_id = $1", npc_id)
    if row is None:
        return None
    return json.loads(row["data"])


async def get_npcs_at_location(
    location_id: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> list[dict]:
    _conn = conn or await db.get_pool()
    rows = await _conn.fetch(
        """
        SELECT id, data FROM npcs
        WHERE EXISTS (
            SELECT 1 FROM jsonb_each_text(data->'schedule') AS s(k, v)
            WHERE v = $1
        )
        """,
        location_id,
    )
    return [{"id": row["id"], **json.loads(row["data"])} for row in rows]


async def get_targets_at_location(
    location_id: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> list[dict]:
    _conn = conn or await db.get_pool()
    rows = await _conn.fetch(
        "SELECT npc_id, data FROM npc_state WHERE data->>'location' = $1",
        location_id,
    )
    return [{"npc_id": row["npc_id"], **json.loads(row["data"])} for row in rows]


async def get_player_inventory(player_id: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None) -> list[dict]:
    _conn = conn or await db.get_pool()
    rows = await _conn.fetch(
        """
        SELECT i.data AS item_data, pi.data AS slot_data
        FROM player_inventory pi
        JOIN items i ON i.id = pi.item_id
        WHERE pi.player_id = $1
        """,
        player_id,
    )
    results = []
    for row in rows:
        item = json.loads(row["item_data"])
        slot = json.loads(row["slot_data"])
        item["slot_info"] = slot
        image_url = db._compute_item_image_url(item)
        if image_url:
            item["image_url"] = image_url
        results.append(item)
    return results


async def get_skill_advancement(
    player_id: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> dict[str, dict]:
    """Fetch all skill advancement data for a player.

    Returns dict keyed by skill_id: {"tier": str, "use_counter": int, "narrative_moment_ready": bool}
    """
    _conn = conn or await db.get_pool()
    rows = await _conn.fetch(
        "SELECT skill_id, tier, use_counter, narrative_moment_ready FROM skill_advancement WHERE player_id = $1",
        player_id,
    )
    return {
        row["skill_id"]: {
            "tier": row["tier"],
            "use_counter": row["use_counter"],
            "narrative_moment_ready": row["narrative_moment_ready"],
        }
        for row in rows
    }


async def get_single_skill_advancement(
    player_id: str, skill: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> dict:
    """Fetch advancement data for a single skill. Returns {tier, use_counter, narrative_moment_ready} or defaults."""
    _conn = conn or await db.get_pool()
    row = await _conn.fetchrow(
        "SELECT tier, use_counter, narrative_moment_ready FROM skill_advancement WHERE player_id = $1 AND skill_id = $2",
        player_id,
        skill,
    )
    if row is None:
        return {"tier": "untrained", "use_counter": 0, "narrative_moment_ready": False}
    return {
        "tier": row["tier"],
        "use_counter": row["use_counter"],
        "narrative_moment_ready": row["narrative_moment_ready"],
    }


async def get_inventory_item(
    player_id: str,
    item_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
    for_update: bool = False,
) -> dict | None:
    _conn = conn or await db.get_pool()
    sql = "SELECT data FROM player_inventory WHERE player_id = $1 AND item_id = $2"
    if for_update:
        sql += " FOR UPDATE"
    row = await _conn.fetchrow(sql, player_id, item_id)
    if row is None:
        return None
    return json.loads(row["data"])


# --- Quest state ---


async def get_player_quest(
    player_id: str,
    quest_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
    for_update: bool = False,
) -> dict | None:
    _conn = conn or await db.get_pool()
    sql = "SELECT data FROM player_quests WHERE player_id = $1 AND quest_id = $2"
    if for_update:
        sql += " FOR UPDATE"
    row = await _conn.fetchrow(sql, player_id, quest_id)
    if row is None:
        return None
    return json.loads(row["data"])


async def get_active_player_quests(
    player_id: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> list[dict]:
    _conn = conn or await db.get_pool()
    rows = await _conn.fetch(
        """
        SELECT pq.quest_id, pq.data AS pq_data, q.data AS q_data
        FROM player_quests pq
        JOIN quests q ON q.id = pq.quest_id
        WHERE pq.player_id = $1
          AND COALESCE(pq.data->>'status', 'active') = 'active'
        """,
        player_id,
    )
    results = []
    for row in rows:
        pq = json.loads(row["pq_data"])
        quest = json.loads(row["q_data"])
        current_stage = pq.get("current_stage", 0)
        stages = quest.get("stages", [])
        results.append(
            {
                "quest_id": row["quest_id"],
                "quest_name": quest.get("name", row["quest_id"]),
                "current_stage": current_stage,
                "stages": stages,
                "scene_graph": quest.get("scene_graph", []),
            }
        )
    return results


async def get_player_flag(
    player_id: str,
    flag: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> bool:
    _conn = conn or await db.get_pool()
    row = await _conn.fetchrow(
        "SELECT data->'flags'->>$2 AS val FROM players WHERE player_id = $1",
        player_id,
        flag,
    )
    if row is None or row["val"] is None:
        return False
    return row["val"] == "true"


async def get_player_flag_value(
    player_id: str,
    flag: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> bool | str | int | None:
    _conn = conn or await db.get_pool()
    row = await _conn.fetchrow(
        "SELECT data->'flags'->$2 AS val FROM players WHERE player_id = $1",
        player_id,
        flag,
    )
    if row is None or row["val"] is None:
        return None
    return json.loads(row["val"])


async def _enrich_quests_with_scene_hints(quests: list[dict]) -> list[dict]:
    """Add 'hints' from scene beats to each quest's data for client display."""
    from scene_tools import _resolve_scene_from_graph

    scene_ids: list[str] = []
    for q in quests:
        for entry in q.get("scene_graph", []):
            sid = entry.get("scene_id")
            if sid and sid not in scene_ids:
                scene_ids.append(sid)
    if not scene_ids:
        return quests

    scene_cache = await db_content_queries.get_scenes_batch(scene_ids)
    for q in quests:
        scene = _resolve_scene_from_graph(scene_cache, q, q.get("current_stage", 0))
        hints: list[str] = []
        if scene:
            for beat in scene.get("beats", []):
                hints.extend(beat.get("companion_hints", []))
        q["hints"] = hints
    return quests


async def get_session_init_payload(player_id: str) -> dict:
    """Build the full session_init payload for a player."""
    # Fetch player first (need location_id), then parallelize the rest
    player = await get_player(player_id)
    location_id = player.get("location_id", "") if player else ""

    location, inventory, quests, map_progress = await asyncio.gather(
        db_content_queries.get_location(location_id) if location_id else asyncio.sleep(0),
        get_player_inventory(player_id),
        get_active_player_quests(player_id),
        db_activity_queries.get_player_map_progress(player_id),
    )

    # Enrich quests with scene beat hints for client display
    quests = await _enrich_quests_with_scene_hints(quests)

    # Build portraits dict
    portraits = db._build_portraits(player, location_id)

    return {
        "character": player,
        "location": location if location_id else None,
        "quests": quests,
        "inventory": inventory,
        "map_progress": map_progress,
        "world_state": {"time": "evening"},
        "portraits": portraits,
    }


async def get_last_session_summary(
    player_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> dict | None:
    """Return the most recent session summary for a player, or None."""
    _conn = conn or await db.get_pool()
    row = await _conn.fetchrow(
        """
        SELECT data FROM session_summaries
        WHERE player_id = $1
        ORDER BY created_at DESC
        LIMIT 1
        """,
        player_id,
    )
    if row is None:
        return None
    return json.loads(row["data"])
