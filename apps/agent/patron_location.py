"""Shared authoritative map-history fact for Nythera's checks and casts."""

import json

import db


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
