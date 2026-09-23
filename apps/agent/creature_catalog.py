"""Internal reads of the seeded creature catalog."""

import json

import db
from world_regions import REGION_IDS


class CreatureNotFoundError(LookupError):
    """A requested creature id has no catalog row."""


async def query_creature_by_id(creature_id: str) -> dict:
    pool = await db.get_pool()
    row = await pool.fetchrow("SELECT data FROM creatures WHERE id = $1", creature_id)
    if row is None:
        raise CreatureNotFoundError(creature_id)
    return json.loads(row["data"])


async def query_creatures_by_region(region_id: str, tier: int | None = None) -> list[dict]:
    if region_id not in REGION_IDS:
        raise ValueError(f"Unknown region: {region_id}")
    pool = await db.get_pool()
    rows = await pool.fetch(
        "SELECT data FROM creatures WHERE data->'regions' @> $1::jsonb "
        "AND ($2::integer IS NULL OR tier = $2) ORDER BY id",
        json.dumps([region_id]),
        tier,
    )
    return [json.loads(row["data"]) for row in rows]
