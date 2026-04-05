"""Database read queries. All async, accept optional conn parameter."""

import asyncio
import json
import logging

import asyncpg

import db

logger = logging.getLogger("divineruin.db")


async def get_location(location_id: str) -> dict | None:
    cache_key = f"location:{location_id}"
    cached = await db._cache_get(cache_key)
    if cached is not None:
        return json.loads(cached)

    pool = await db.get_pool()
    row = await pool.fetchrow("SELECT data FROM locations WHERE id = $1", location_id)
    if row is None:
        return None

    data = json.loads(row["data"])
    await db._cache_set(cache_key, json.dumps(data))
    return data


async def get_location_region_type(location_id: str) -> str:
    """Return the region_type for a location ('city', 'wilderness', or 'dungeon').

    Falls back to 'city' if the location is not found or has no region_type.
    """
    from region_types import REGION_CITY

    location = await get_location(location_id)
    if location is None:
        return REGION_CITY
    return location.get("region_type", REGION_CITY)


async def get_npc(npc_id: str) -> dict | None:
    cache_key = f"npc:{npc_id}"
    cached = await db._cache_get(cache_key)
    if cached is not None:
        return json.loads(cached)

    pool = await db.get_pool()
    row = await pool.fetchrow("SELECT data FROM npcs WHERE id = $1", npc_id)
    if row is None:
        return None

    data = json.loads(row["data"])
    await db._cache_set(cache_key, json.dumps(data))
    return data


async def get_item(item_id: str) -> dict | None:
    cache_key = f"item:{item_id}"
    cached = await db._cache_get(cache_key)
    if cached is not None:
        return json.loads(cached)

    pool = await db.get_pool()
    row = await pool.fetchrow("SELECT data FROM items WHERE id = $1", item_id)
    if row is None:
        return None

    data = json.loads(row["data"])
    await db._cache_set(cache_key, json.dumps(data))
    return data


async def search_lore(keyword: str, limit: int = 5) -> list[dict]:
    keyword = keyword[:256]
    # Escape ILIKE metacharacters
    escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    limit = max(1, min(limit, 100))
    pool = await db.get_pool()
    rows = await pool.fetch(
        "SELECT data FROM lore_entries WHERE data::text ILIKE $1 LIMIT $2",
        f"%{escaped}%",
        limit,
    )
    return [json.loads(row["data"]) for row in rows]


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
        logger.warning("Double-encoded player data for %s — run data migration", player_id)
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


# --- Content queries (cached) ---


async def get_quest(quest_id: str) -> dict | None:
    cache_key = f"quest:{quest_id}"
    cached = await db._cache_get(cache_key)
    if cached is not None:
        return json.loads(cached)

    pool = await db.get_pool()
    row = await pool.fetchrow("SELECT data FROM quests WHERE id = $1", quest_id)
    if row is None:
        return None

    data = json.loads(row["data"])
    await db._cache_set(cache_key, json.dumps(data))
    return data


async def get_scene(scene_id: str) -> dict | None:
    cache_key = f"scene:{scene_id}"
    cached = await db._cache_get(cache_key)
    if cached is not None:
        return json.loads(cached)

    pool = await db.get_pool()
    row = await pool.fetchrow("SELECT data FROM scenes WHERE id = $1", scene_id)
    if row is None:
        return None

    data = json.loads(row["data"])
    await db._cache_set(cache_key, json.dumps(data))
    return data


async def get_scenes_batch(scene_ids: list[str]) -> dict[str, dict]:
    """Fetch multiple scenes by ID, returning a dict mapping scene_id → scene data."""
    if not scene_ids:
        return {}
    # Check cache first for each id, collect misses
    result: dict[str, dict] = {}
    missing: list[str] = []
    for sid in scene_ids:
        cached = await db._cache_get(f"scene:{sid}")
        if cached is not None:
            result[sid] = json.loads(cached)
        else:
            missing.append(sid)
    # Batch-fetch misses with single query (mirrors get_npc_dispositions pattern)
    if missing:
        pool = await db.get_pool()
        rows = await pool.fetch("SELECT id, data FROM scenes WHERE id = ANY($1)", missing)
        for row in rows:
            data = json.loads(row["data"])
            result[row["id"]] = data
            await db._cache_set(f"scene:{row['id']}", json.dumps(data))
    return result


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


# --- Combat state ---


async def get_encounter_template(encounter_id: str) -> dict | None:
    cache_key = f"encounter:{encounter_id}"
    cached = await db._cache_get(cache_key)
    if cached is not None:
        return json.loads(cached)

    pool = await db.get_pool()
    row = await pool.fetchrow("SELECT data FROM encounter_templates WHERE id = $1", encounter_id)
    if row is None:
        return None

    data = json.loads(row["data"])
    await db._cache_set(cache_key, json.dumps(data))
    return data


async def get_player_map_progress(player_id: str) -> list[dict]:
    """Return all visited locations for a player."""
    pool = await db.get_pool()
    rows = await pool.fetch(
        "SELECT location_id, data FROM player_map_progress WHERE player_id = $1",
        player_id,
    )
    return [
        {
            "location_id": row["location_id"],
            "connections": json.loads(row["data"]).get("connections", []),
        }
        for row in rows
    ]


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

    scene_cache = await get_scenes_batch(scene_ids)
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
        get_location(location_id) if location_id else asyncio.sleep(0),
        get_player_inventory(player_id),
        get_active_player_quests(player_id),
        get_player_map_progress(player_id),
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


# --- Async activities ---


async def get_player_activities(
    player_id: str, status: str | None = None, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> list[dict]:
    """Get all activities for a player, optionally filtered by status."""
    _conn = conn or await db.get_pool()
    if status:
        rows = await _conn.fetch(
            "SELECT id, data FROM async_activities WHERE player_id = $1 AND data->>'status' = $2 ORDER BY created_at DESC",
            player_id,
            status,
        )
    else:
        rows = await _conn.fetch(
            "SELECT id, data FROM async_activities WHERE player_id = $1 ORDER BY created_at DESC",
            player_id,
        )
    return [{"id": row["id"], **json.loads(row["data"])} for row in rows]


async def get_activity(
    activity_id: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None, for_update: bool = False
) -> dict | None:
    """Get a single activity by ID."""
    _conn = conn or await db.get_pool()
    sql_query = "SELECT id, player_id, data FROM async_activities WHERE id = $1"
    if for_update:
        sql_query += " FOR UPDATE"
    row = await _conn.fetchrow(sql_query, activity_id)
    if row is None:
        return None
    return {"id": row["id"], "player_id": row["player_id"], **json.loads(row["data"])}


async def get_due_activities(*, conn: asyncpg.Connection | asyncpg.Pool | None = None) -> list[dict]:
    """Find activities where resolve_at <= NOW() and status is 'in_progress'."""
    _conn = conn or await db.get_pool()
    rows = await _conn.fetch(
        """
        SELECT id, player_id, data FROM async_activities
        WHERE data->>'status' = 'in_progress'
          AND (data->>'resolve_at')::timestamptz <= NOW()
        ORDER BY (data->>'resolve_at')::timestamptz ASC
        """,
    )
    return [{"id": row["id"], "player_id": row["player_id"], **json.loads(row["data"])} for row in rows]


async def count_active_activities(player_id: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None) -> int:
    """Count in-progress activities for a player."""
    _conn = conn or await db.get_pool()
    row = await _conn.fetchrow(
        "SELECT COUNT(*) AS cnt FROM async_activities WHERE player_id = $1 AND data->>'status' = 'in_progress'",
        player_id,
    )
    return row["cnt"] if row else 0


# --- Player creation ---


async def player_exists(player_id: str) -> bool:
    """Check if player row exists without loading full data."""
    pool = await db.get_pool()
    row = await pool.fetchrow(
        "SELECT 1 FROM players WHERE player_id = $1",
        player_id,
    )
    return row is not None


# --- Divine favor ---


async def get_divine_favor(player_id: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None) -> dict | None:
    """Read divine_favor from player JSONB data."""
    _conn = conn or await db.get_pool()
    row = await _conn.fetchrow(
        "SELECT data->'divine_favor' AS favor FROM players WHERE player_id = $1",
        player_id,
    )
    if row is None or row["favor"] is None:
        return None
    return json.loads(row["favor"])


async def get_pending_god_whispers(player_id: str) -> list[dict]:
    """Return all pending god whispers for a player."""
    pool = await db.get_pool()
    rows = await pool.fetch(
        """
        SELECT id, data FROM god_whispers
        WHERE player_id = $1 AND data->>'status' = 'pending'
        ORDER BY created_at DESC
        """,
        player_id,
    )
    return [{"id": row["id"], **json.loads(row["data"])} for row in rows]


async def get_session_story_moments(
    session_id: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> list[dict]:
    """Return all story moments for a session, ordered by creation time."""
    _conn = conn or await db.get_pool()
    rows = await _conn.fetch(
        """
        SELECT moment_key, description, template_id, asset_id
        FROM story_moments
        WHERE session_id = $1
        ORDER BY created_at ASC
        """,
        session_id,
    )
    return [
        {
            "moment_key": row["moment_key"],
            "description": row["description"],
            "template_id": row["template_id"],
            "asset_id": row["asset_id"],
        }
        for row in rows
    ]


async def count_session_story_moments(session_id: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None) -> int:
    """Count story moments in a session."""
    _conn = conn or await db.get_pool()
    row = await _conn.fetchrow(
        "SELECT COUNT(*) AS cnt FROM story_moments WHERE session_id = $1",
        session_id,
    )
    return row["cnt"] if row else 0
