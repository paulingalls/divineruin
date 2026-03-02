"""Database and Redis connection layer with cached entity queries."""

import json
import logging
import os

import asyncpg
import redis.asyncio as aioredis

logger = logging.getLogger("divineruin.db")

CACHE_TTL = 300  # 5 minutes

_pool: asyncpg.Pool | None = None
_redis: aioredis.Redis | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])
    return _pool


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379"),
            decode_responses=True,
        )
    return _redis


async def close_all() -> None:
    global _pool, _redis
    if _pool is not None:
        await _pool.close()
        _pool = None
    if _redis is not None:
        await _redis.aclose()
        _redis = None


async def _cache_get(key: str) -> str | None:
    try:
        r = await get_redis()
        return await r.get(key)
    except Exception:
        logger.warning("Redis read failed for key %s, falling through to DB", key)
        return None


async def _cache_set(key: str, value: str) -> None:
    try:
        r = await get_redis()
        await r.set(key, value, ex=CACHE_TTL)
    except Exception:
        logger.warning("Redis write failed for key %s", key)


# --- Content queries (cached) ---


async def get_location(location_id: str) -> dict | None:
    cache_key = f"location:{location_id}"
    cached = await _cache_get(cache_key)
    if cached is not None:
        return json.loads(cached)

    pool = await get_pool()
    row = await pool.fetchrow("SELECT data FROM locations WHERE id = $1", location_id)
    if row is None:
        return None

    data = json.loads(row["data"])
    await _cache_set(cache_key, json.dumps(data))
    return data


async def get_npc(npc_id: str) -> dict | None:
    cache_key = f"npc:{npc_id}"
    cached = await _cache_get(cache_key)
    if cached is not None:
        return json.loads(cached)

    pool = await get_pool()
    row = await pool.fetchrow("SELECT data FROM npcs WHERE id = $1", npc_id)
    if row is None:
        return None

    data = json.loads(row["data"])
    await _cache_set(cache_key, json.dumps(data))
    return data


async def get_item(item_id: str) -> dict | None:
    cache_key = f"item:{item_id}"
    cached = await _cache_get(cache_key)
    if cached is not None:
        return json.loads(cached)

    pool = await get_pool()
    row = await pool.fetchrow("SELECT data FROM items WHERE id = $1", item_id)
    if row is None:
        return None

    data = json.loads(row["data"])
    await _cache_set(cache_key, json.dumps(data))
    return data


async def search_lore(keyword: str, limit: int = 5) -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT data FROM lore_entries WHERE data::text ILIKE $1 LIMIT $2",
        f"%{keyword}%",
        limit,
    )
    return [json.loads(row["data"]) for row in rows]


# --- State queries (not cached) ---


async def get_npc_disposition(npc_id: str, player_id: str) -> str | None:
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT data FROM npc_dispositions WHERE npc_id = $1 AND player_id = $2",
        npc_id,
        player_id,
    )
    if row is None:
        return None
    data = json.loads(row["data"])
    return data.get("disposition")


async def get_player(player_id: str) -> dict | None:
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT data FROM players WHERE player_id = $1", player_id
    )
    if row is None:
        return None
    return json.loads(row["data"])


async def update_player_hp(player_id: str, current_hp: int) -> None:
    pool = await get_pool()
    await pool.execute(
        """
        UPDATE players
        SET data = jsonb_set(data, '{hp,current}', $2::jsonb)
        WHERE player_id = $1
        """,
        player_id,
        json.dumps(current_hp),
    )


async def get_npc_combat_stats(npc_id: str) -> dict | None:
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT data FROM npc_state WHERE npc_id = $1", npc_id
    )
    if row is None:
        return None
    return json.loads(row["data"])


async def update_npc_hp(npc_id: str, current_hp: int) -> None:
    pool = await get_pool()
    await pool.execute(
        """
        UPDATE npc_state
        SET data = jsonb_set(data, '{hp,current}', $2::jsonb)
        WHERE npc_id = $1
        """,
        npc_id,
        json.dumps(current_hp),
    )


async def get_npcs_at_location(location_id: str) -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(
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


async def get_targets_at_location(location_id: str) -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT npc_id, data FROM npc_state WHERE data->>'location' = $1",
        location_id,
    )
    return [{"npc_id": row["npc_id"], **json.loads(row["data"])} for row in rows]


async def get_player_inventory(player_id: str) -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(
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
        results.append(item)
    return results
