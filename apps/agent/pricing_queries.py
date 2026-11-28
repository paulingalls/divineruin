"""Cached economic-pricing lookup (the DB-loaded SSOT).

content/pricing.json -> `pricing` table (id='economy'), seeded by
scripts/seed_content.py and read by both TS (apps/server/src/pricing.ts) and here.
Holds the cross-language economic constants — repair cost by rarity, disposition
price multipliers, silver/gold — so they live in one place instead of being
hand-mirrored. Uses db._cache_get/_cache_set for Redis caching, mirroring
db_content_queries. The pure pricing math (durability.calculate_repair_cost,
workspace.compute_rental_price) takes these values as params, so it stays
synchronous and deterministic; this async layer just fetches the table.
"""

import json
import logging

import asyncpg

import db
from economy_pricing import parse_economy_pricing

logger = logging.getLogger("divineruin.db")

_ECONOMY_ID = "economy"


async def get_economy_pricing(*, conn: asyncpg.Connection | None = None) -> dict:
    """Return the `economy` pricing row for repair, sales and currency conversion.

    Fail loud if the row is absent — every priced tool depends on it, so a missing
    row is a seed/migration misconfiguration, not a runtime-absent lookup.
    """
    cache_key = f"pricing:{_ECONOMY_ID}"
    cached = await db._cache_get(cache_key)
    if cached is not None:
        return parse_economy_pricing(json.loads(cached))

    connection = conn or await db.get_pool()
    row = await connection.fetchrow("SELECT data FROM pricing WHERE id = $1", _ECONOMY_ID)
    if row is None:
        raise RuntimeError("pricing: no 'economy' row in the pricing table (run seed_content)")

    data = parse_economy_pricing(json.loads(row["data"]))
    await db._cache_set(cache_key, json.dumps(data))
    return data
