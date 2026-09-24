"""Database and Redis connection layer with cached entity queries."""

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

import asyncpg
import redis.asyncio as aioredis

import npcs
from asset_utils import slug_asset_url
from companion_profiles import get_companion_profile, select_companion_for_archetype

logger = logging.getLogger("divineruin.db")

CACHE_TTL = 300  # 5 minutes

_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock()
_redis: aioredis.Redis | None = None
_redis_lock = asyncio.Lock()

_CONNECT_ATTEMPTS = 3
_CONNECT_BACKOFF_SECONDS = 0.25  # linear: 0.25s, then 0.5s
# Per-ATTEMPT connect timeout. asyncpg's own default is 60s, which retrying would
# have turned into a 3x180s worst case for a black-holed (dropped, not refused) TCP
# connect — while the warm-up attempt holds _pool_lock and every get_pool() caller
# queues behind it. 3 x 20s keeps the total at the pre-retry 60s.
_CONNECT_TIMEOUT_SECONDS = 20

_TRANSIENT_CONNECT_ERRORS = (
    OSError,  # includes ConnectionError — the "rejected SSL upgrade" case
    asyncpg.CannotConnectNowError,  # server still starting up
    asyncpg.TooManyConnectionsError,  # momentary connection-slot exhaustion
)


async def _connect_with_retry(*args: object, **kwargs: object) -> asyncpg.Connection:
    """Connect hook for asyncpg's pool with bounded retry on transient setup errors.

    Passed as create_pool(connect=...) so every connection the pool opens routes
    through the retry: the min_size warm-up AND each later acquire-time
    connection (asyncpg's Pool._get_new_connection always calls this hook).
    Retrying around the create_pool() call instead would only cover startup.

    Each attempt is bounded by _CONNECT_TIMEOUT_SECONDS (setdefault, so an explicit
    caller timeout still wins) — without it, retrying would multiply asyncpg's 60s
    default into a 180s hang on a black-holed connect.
    """
    for attempt in range(_CONNECT_ATTEMPTS):
        try:
            kwargs.setdefault("timeout", _CONNECT_TIMEOUT_SECONDS)
            return await asyncpg.connect(*args, **kwargs)
        except _TRANSIENT_CONNECT_ERRORS as e:
            if attempt >= _CONNECT_ATTEMPTS - 1:
                raise
            logger.warning(
                "Transient DB connect error on attempt %d/%d: %s",
                attempt + 1,
                _CONNECT_ATTEMPTS,
                e,
            )
            await asyncio.sleep(_CONNECT_BACKOFF_SECONDS * (attempt + 1))
    raise AssertionError("unreachable")


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool
    async with _pool_lock:
        if _pool is None:
            database_url = os.environ.get("DATABASE_URL")
            if not database_url:
                raise RuntimeError("DATABASE_URL is not set")
            _pool = await asyncpg.create_pool(
                database_url,
                min_size=2,
                max_size=5,
                connect=_connect_with_retry,
            )
        return _pool


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is not None:
        return _redis
    async with _redis_lock:
        if _redis is None:
            redis_url = os.environ.get("REDIS_URL")
            if not redis_url:
                raise RuntimeError("REDIS_URL is not set")
            _redis = aioredis.from_url(
                redis_url,
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
            yield cast(asyncpg.Connection, conn)


DESYNCED_REPLY_LOG = "Redis GET %s answered %r, not a string: discarding the desynced client (pool %r, loop %#x)"


async def _cache_get(key: str) -> str | None:
    try:
        r = await get_redis()
        value = await r.get(key)
    except Exception:
        logger.warning("Redis read failed for key %s, falling through to DB", key)
        return None
    if value is None or isinstance(value, str):
        return value
    await _discard_desynced_redis(r, key, value)
    return None


async def _discard_desynced_redis(r: aioredis.Redis, key: str, reply: object) -> None:
    """Drop a client whose GET was answered with a non-string.

    A GET that echoes its own command indicates a TCP self-connect. Other non-string replies
    also leave the connection untrustworthy. A wrong string reply remains undetectable here.
    """
    global _redis
    if reply == ["GET", key]:
        logger.error("Redis GET %s hit a TCP self-connect: echoed %r", key, reply)
    logger.error(DESYNCED_REPLY_LOG, key, reply, r.connection_pool, id(asyncio.get_running_loop()))
    if _redis is r:
        _redis = None
    try:
        await r.connection_pool.disconnect()
    except Exception:
        logger.exception("Disconnecting the desynced Redis pool failed")


async def _cache_set(key: str, value: str) -> None:
    try:
        r = await get_redis()
        await r.set(key, value, ex=CACHE_TTL)
    except Exception:
        logger.warning("Redis write failed for key %s", key)


# --- State mutations ---


def extract_exit_connections(exits: dict) -> list[str]:
    """Extract destination IDs from a location's exits dict."""
    connections = []
    for exit_data in exits.values():
        dest = exit_data.get("destination", "") if isinstance(exit_data, dict) else str(exit_data)
        if dest:
            connections.append(dest)
    return connections


def resolve_player_companion_id(player: dict | None) -> str | None:
    """The companion assigned to this player, from their archetype. None when unresolvable.

    An archetype that matches no companion is already fatal at session start (agent.py's
    dm_session raises), so this does not raise a second time: its callers are payload builders
    whose own caller logs and continues, and raising here would drop the whole session_init —
    character sheet, inventory, quests and map — over one field.
    """
    archetype = (player or {}).get("class")
    if not archetype:
        return None
    try:
        return select_companion_for_archetype(archetype)
    except ValueError:
        logger.warning("No companion resolves for archetype %r; session_init ships a null companion", archetype)
        return None


def _build_portraits(companion_id: str | None) -> dict:
    """Build the portraits payload for session_init, keyed on the player's assigned companion.

    Takes the already-resolved id rather than the player row so the payload's `companion` block
    and its portrait can never name two different companions.

    A companion with no authored portrait yields an explicit None. The client must clear its
    portrait store on that null so the previous companion's face cannot survive a player change.
    """
    npc_portraits = {
        npc["voice_id"]: {
            "name": npc["name"],
            "url": slug_asset_url(npc["portrait"]),
        }
        for npc in npcs.all_npcs()
        if "portrait" in npc
    }
    companion_portrait = None
    if companion_id is not None:
        portrait = get_companion_profile(companion_id).portrait
        if portrait is not None:
            companion_portrait = {
                "primary": slug_asset_url(portrait.primary),
                "alert": slug_asset_url(portrait.alert),
            }
    return {
        "npcs": npc_portraits,
        "companion": companion_portrait,
    }
