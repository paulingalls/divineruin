"""Location and map-history facts for patron effects."""

import json

import asyncpg

import db
from db_content_queries import get_location


async def is_coastal_location(location_id: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None) -> bool:
    location = await get_location(location_id, conn=conn)
    if location is None:
        raise ValueError(f"Unknown location {location_id!r}")
    return location["region"] == "sunward_coast"


async def is_sanctuary_location(location_id: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None) -> bool:
    location = await get_location(location_id, conn=conn)
    if location is None:
        raise ValueError(f"Unknown location {location_id!r}")
    return "sanctuary" in location.get("tags", ())


async def first_stay_at_location(player_id: str, location_id: str, *, conn=None) -> bool:
    source = conn if conn is not None else await db.get_pool()
    row = await source.fetchrow(
        "SELECT data FROM player_map_progress WHERE player_id = $1 AND location_id = $2",
        player_id,
        location_id,
    )
    if row is None:
        return False
    data = row["data"]
    if isinstance(data, str):
        data = json.loads(data)
    return not data.get("revisited", False)


async def check_first_stay(player, session, skill, *, player_id: str, conn=None) -> bool:
    if (player.get("divine_favor") or {}).get("patron") != "nythera":
        return False
    if skill.lower() not in {"investigation", "perception", "animal_handling"}:
        return False
    return await first_stay_at_location(player_id, session.location_id, conn=conn)
