"""Cached materials-catalog accessor for the DM agent (M5.2 crafting).

The Python agent reads the materials catalog from the DB (constraint 8508fdb1abc3,
wisdom bb73edd9b94d) — content/materials_catalog.json -> materials_catalog table
(migration 019), seeded by scripts/seed_content.py. Mirrors recipes.py: a fail-loud
parse_material_row, cached get_material / list_materials accessors keyed
material:<id> and materials:all.

get_materials_catalog returns the {material_id: {id, category, tier}} map that the
pre-flight pipeline's Check 4 (check_material_requirements) and the craft-consume
allocator (recipe_validation.allocate_materials) take as their `catalog` arg.
"""

import json

import db

# Canonical material tier scale (1-4). Single source of truth for both a material's
# own `tier` (here) and a recipe's MaterialReq.tier_minimum (recipes.py imports this),
# so the scale can't drift between the two parsers (wisdom bb73edd9b94d).
MATERIAL_TIERS = {1, 2, 3, 4}


def parse_material_row(material_id: str, raw: object) -> dict:
    """Validate one materials_catalog row's `data`, returning {id, category, tier}.

    Fail-loud at the load boundary: a content typo (bad category/tier) raises here
    rather than surfacing as a silent mis-gate in crafting. category is an open
    content vocabulary (metal/wood/herb/...), so only non-emptiness is enforced;
    tier is the closed 1-4 scale (bool rejected — a tier is never True/False)."""
    if not isinstance(raw, dict):
        raise ValueError(f"materials_catalog[{material_id}] data is not an object")
    category = raw.get("category")
    if not isinstance(category, str) or len(category) == 0:
        raise ValueError(f"materials_catalog[{material_id}].category is not a non-empty string")
    tier = raw.get("tier")
    if isinstance(tier, bool) or not isinstance(tier, int) or tier not in MATERIAL_TIERS:
        raise ValueError(f"materials_catalog[{material_id}].tier {tier!r} is not 1-4")
    return {"id": material_id, "category": category, "tier": tier}


async def get_material(material_id: str) -> dict | None:
    """Return the parsed material for material_id, or None if unknown.

    Caches the PARSED dict (parse-once), mirroring recipes.get_recipe."""
    cache_key = f"material:{material_id}"
    cached = await db._cache_get(cache_key)
    if cached is not None:
        return json.loads(cached)

    pool = await db.get_pool()
    row = await pool.fetchrow("SELECT data FROM materials_catalog WHERE id = $1", material_id)
    if row is None:
        return None

    material = parse_material_row(material_id, json.loads(row["data"]))
    await db._cache_set(cache_key, json.dumps(material))
    return material


async def list_materials() -> list[dict]:
    """Return all parsed materials, cached under materials:all."""
    cache_key = "materials:all"
    cached = await db._cache_get(cache_key)
    if cached is not None:
        return json.loads(cached)

    pool = await db.get_pool()
    rows = await pool.fetch("SELECT id, data FROM materials_catalog ORDER BY id")
    parsed = [parse_material_row(r["id"], json.loads(r["data"])) for r in rows]
    await db._cache_set(cache_key, json.dumps(parsed))
    return parsed


async def get_materials_catalog() -> dict[str, dict]:
    """Return the {material_id: {id, category, tier}} map consumed by the pre-flight
    materials gate + the craft-consume allocator."""
    return {m["id"]: m for m in await list_materials()}
