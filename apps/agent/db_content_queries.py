"""Cached content lookup queries (locations, NPCs, items, lore, quests, scenes, encounters).

All functions use db._cache_get() / db._cache_set() for Redis caching.
No conn parameter — these read from the pool and cache layer.
"""

import json
import logging

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
    """Fetch multiple scenes by ID, returning a dict mapping scene_id -> scene data."""
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
