"""Cached recipe-slot reference data for the DM agent (M5.1 crafting).

recipe_slots is small static reference data (one row per Crafting skill tier),
seeded inline by migration 019. The slot caps live in exactly one place — the DB
— and both languages read them from there (concern d125d022f084, Golden Rule #4).
The Python validator (recipe_validation.validate_recipe_slot_capacity) is pure and
takes this mapping as an arg; _learn_recipe_impl loads it here and passes it in.

Mirrors recipes.py: a fail-loud parse_recipe_slot_row plus a cached get_recipe_slots
accessor keyed recipe_slots:all.
"""

import json
import logging

import db
from recipe_validation import RECIPE_TIER_ORDER

logger = logging.getLogger("divineruin.recipe_slots")


def parse_recipe_slot_row(slot_id: str, raw: object) -> dict:
    """Validate one recipe_slots-table row's `data` payload, fail-loud.

    `data` = {"max_recipe_tier": <basic|trained|expert|master>,
    "known_recipe_slots": <int >= 0, or null for unlimited (Master)>}. Raises
    ValueError with a `recipe_slots[<id>].<field>` context on any mismatch.
    """
    ctx = f"recipe_slots[{slot_id}]"
    if not isinstance(raw, dict):
        raise ValueError(f"{ctx}.data is not an object")

    max_tier = raw.get("max_recipe_tier")
    if not isinstance(max_tier, str) or max_tier not in RECIPE_TIER_ORDER:
        raise ValueError(f"{ctx}.max_recipe_tier {max_tier!r} is not a valid recipe tier")

    if "known_recipe_slots" not in raw:
        raise ValueError(f"{ctx}.known_recipe_slots is missing")
    cap = raw["known_recipe_slots"]
    # null = unlimited, and ONLY the Master tier is unlimited. A null cap on any
    # other tier is a seed typo (untrained=null would mean unlimited basics), so
    # reject it loudly rather than silently uncapping. Otherwise a real int >= 0;
    # bool is an int subclass in Python, so reject it explicitly — never True/False.
    if cap is None:
        if max_tier != "master":
            raise ValueError(f"{ctx}.known_recipe_slots null (unlimited) is only valid for the master tier")
    elif isinstance(cap, bool) or not isinstance(cap, int) or cap < 0:
        raise ValueError(f"{ctx}.known_recipe_slots {cap!r} is not null or an integer >= 0")

    return {"max_recipe_tier": max_tier, "known_recipe_slots": cap}


async def get_recipe_slots() -> dict[str, dict]:
    """Return the recipe-slot caps keyed by Crafting tier, cached under recipe_slots:all.

    crafting_tier -> {"max_recipe_tier": str, "known_recipe_slots": int | None}.
    """
    cache_key = "recipe_slots:all"
    cached = await db._cache_get(cache_key)
    if cached is not None:
        return json.loads(cached)

    pool = await db.get_pool()
    rows = await pool.fetch("SELECT id, data FROM recipe_slots")
    slots = {r["id"]: parse_recipe_slot_row(r["id"], json.loads(r["data"])) for r in rows}
    await db._cache_set(cache_key, json.dumps(slots))
    return slots
