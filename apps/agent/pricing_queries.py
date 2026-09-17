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
import math

import db

logger = logging.getLogger("divineruin.db")

_ECONOMY_ID = "economy"
MAX_DISPOSITION_MULTIPLIER = 1e304
DISPOSITION_MULTIPLIER_CAP_RULE = f"must be <= {MAX_DISPOSITION_MULTIPLIER}"


def _as_json_number(value: int | float) -> float:
    """The value as the TS parser sees it: JSON.parse collapses a literal outside
    float range to Infinity, while Python keeps an unbounded int and then raises a
    bare OverflowError on the first float op. Mirror JS so both refuse the same row
    with the same rule (constraint 7).
    """
    try:
        return float(value)
    except OverflowError:
        return math.inf


def _validate_economy_pricing(data: dict) -> dict:
    for key, value in data["disposition_multipliers"].items():
        ctx = f"pricing[economy].disposition_multipliers.{key}"
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{ctx} must be a number")
        value = _as_json_number(value)
        if not math.isfinite(value):
            raise ValueError(f"{ctx} must be finite")
        if value < 0:
            raise ValueError(f"{ctx} must be >= 0")
        if value > MAX_DISPOSITION_MULTIPLIER:
            raise ValueError(f"{ctx} {DISPOSITION_MULTIPLIER_CAP_RULE}")
        if abs(value * 10_000 - round(value * 10_000)) >= 1e-9:
            raise ValueError(f"{ctx} must have at most 4 decimal places")

    for key, value in data["repair_cost_sp"].items():
        ctx = f"pricing[economy].repair_cost_sp.{key}"
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{ctx} must be an integer")
        if not math.isfinite(_as_json_number(value)):
            raise ValueError(f"{ctx} must be an integer")
        if value < 0:
            raise ValueError(f"{ctx} must be >= 0")
    return data


async def get_economy_pricing() -> dict:
    """Return the `economy` pricing row: keys repair_cost_sp (rarity->sp),
    disposition_multipliers (disposition->factor), silver_per_gold (int).

    Fail loud if the row is absent — every priced tool depends on it, so a missing
    row is a seed/migration misconfiguration, not a runtime-absent lookup.
    """
    cache_key = f"pricing:{_ECONOMY_ID}"
    cached = await db._cache_get(cache_key)
    if cached is not None:
        return _validate_economy_pricing(json.loads(cached))

    pool = await db.get_pool()
    row = await pool.fetchrow("SELECT data FROM pricing WHERE id = $1", _ECONOMY_ID)
    if row is None:
        raise RuntimeError("pricing: no 'economy' row in the pricing table (run seed_content)")

    data = _validate_economy_pricing(json.loads(row["data"]))
    await db._cache_set(cache_key, json.dumps(data))
    return data
