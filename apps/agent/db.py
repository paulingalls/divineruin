"""Database and Redis connection layer with cached entity queries."""

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
import redis.asyncio as aioredis

from asset_utils import asset_url, slug_asset_url

logger = logging.getLogger("divineruin.db")

# Pre-generated portrait URLs — slug-based, matching files in assets/images/
_PORTRAITS_CACHE: dict = {
    "companion": {
        "primary": slug_asset_url("companion_kael_primary"),
        "alert": slug_asset_url("companion_kael_alert"),
    },
    "npcs": {
        "Guildmaster Torin": slug_asset_url("npc_torin"),
        "Elder Yanna": slug_asset_url("npc_yanna"),
        "Scholar Emris": slug_asset_url("npc_emris"),
        "Wounded Rider": slug_asset_url("npc_wounded_rider"),
        "Maren": slug_asset_url("npc_maren"),
        "Investigator Valdris": slug_asset_url("npc_valdris"),
        "Grimjaw": slug_asset_url("npc_grimjaw"),
        "Bryn": slug_asset_url("npc_bryn"),
        "Warden Selene": slug_asset_url("npc_selene"),
        "Aldric": slug_asset_url("npc_aldric"),
        "Nyx": slug_asset_url("npc_nyx"),
        "Archivist Theron": slug_asset_url("npc_theron"),
        "Guild Master Dara": slug_asset_url("npc_dara"),
    },
}

CACHE_TTL = 300  # 5 minutes

_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock()
_redis: aioredis.Redis | None = None
_redis_lock = asyncio.Lock()


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool
    async with _pool_lock:
        if _pool is None:
            _pool = await asyncpg.create_pool(
                os.environ["DATABASE_URL"],
                min_size=2,
                max_size=5,
            )
        return _pool


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is not None:
        return _redis
    async with _redis_lock:
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


@asynccontextmanager
async def transaction() -> AsyncIterator[asyncpg.Connection]:
    """Acquire a pooled connection and open a transaction.

    All reads/writes using the yielded connection share a single transaction.
    Commits on clean exit, rolls back on exception.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            yield conn


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


def _compute_item_image_url(item_data: dict) -> str | None:
    """Compute deterministic image URL for an item with art_template."""
    art = item_data.get("art_template")
    if not art or not isinstance(art, dict):
        return None
    template_id = art.get("template_id")
    template_vars = art.get("vars", {})
    if not template_id:
        return None
    return asset_url(template_id, template_vars)


# --- State mutations ---


def extract_exit_connections(exits: dict) -> list[str]:
    """Extract destination IDs from a location's exits dict."""
    connections = []
    for exit_data in exits.values():
        dest = exit_data.get("destination", "") if isinstance(exit_data, dict) else str(exit_data)
        if dest:
            connections.append(dest)
    return connections


def _build_portraits(player: dict | None, location_id: str) -> dict:
    """Build the portraits payload for session_init."""
    return dict(_PORTRAITS_CACHE)
