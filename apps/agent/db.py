"""Database and Redis connection layer with cached entity queries."""

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

import asyncpg
import redis.asyncio as aioredis

from asset_utils import slug_asset_url
from companion_profiles import select_companion_for_archetype

logger = logging.getLogger("divineruin.db")

# Companion portraits, keyed by companion id. Only Kael has a generated asset set
# (assets/images/companion_kael_{primary,alert}.png); Lira/Tam/Sable resolve to None until
# scripts/generate_art.ts produces theirs (debt 9f6a7ada). A missing entry is an explicit null in the
# payload, never a fall-through to whoever happens to have a face.
_COMPANION_PORTRAITS: dict[str, dict[str, str]] = {
    "companion_kael": {
        "primary": slug_asset_url("companion_kael_primary"),
        "alert": slug_asset_url("companion_kael_alert"),
    },
}

# Pre-generated portrait URLs — slug-based, matching files in assets/images/
_PORTRAITS_CACHE: dict = {
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
            _pool = await asyncpg.create_pool(
                os.environ["DATABASE_URL"],
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
            _redis = aioredis.from_url(
                os.environ.get("REDIS_URL", "redis://localhost:56379"),
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

    A companion with no generated asset set yields an explicit None. The client must CLEAR its
    portrait store on that null rather than fall through — falling through is how the previous
    companion's face survives into the next player's HUD.
    """
    return {**_PORTRAITS_CACHE, "companion": _COMPANION_PORTRAITS.get(companion_id or "")}
