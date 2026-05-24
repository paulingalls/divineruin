"""Cached recipe accessors for the DM agent (M5.1 crafting).

The Python agent reads recipes from the DB (constraint 8508fdb1abc3, wisdom
bb73edd9b94d) — never a hardcoded const. This mirrors the TS server's
apps/server/src/recipes.ts: a fail-loud parse_recipe_row validating all 16
Recipe fields (every one required — recipes are fully-specified content), plus
cached get_recipe / list_recipes accessors keyed recipe:<id> and recipes:all.

Read-only from the agent's view: only the TS server writes recipes during
resolution. Consumed by story-006's recipe tools (query_recipe_requirements,
learn_recipe), which read the snake_case parsed dict returned here.
"""

import json
import logging

import db

logger = logging.getLogger("divineruin.recipes")

_CATEGORIES = {"weapon", "armor", "consumable", "tool", "enchantment", "ammunition"}
_TIERS = {"basic", "trained", "expert", "master"}
_WORKSPACES = {"field", "workshop", "forge", "laboratory"}
_MATERIAL_TIERS = {1, 2, 3, 4}


def _require_int_at_least(value: object, min_: int, ctx: str) -> int:
    """Mirror TS requireIntAtLeast: a real int >= min_. bool is an int subclass
    in Python, so reject it explicitly — a count field is never True/False."""
    if isinstance(value, bool) or not isinstance(value, int) or value < min_:
        raise ValueError(f"{ctx} {value!r} is not an integer >= {min_}")
    return value


def _parse_material_req(raw: object, ctx: str) -> dict:
    """Mirror TS parseMaterialReq: validate one MaterialReq in isolation."""
    if not isinstance(raw, dict):
        raise ValueError(f"{ctx} is not an object")
    material_id = raw.get("material_id")
    if not isinstance(material_id, str) or len(material_id) == 0:
        raise ValueError(f"{ctx}.material_id is not a non-empty string")
    quantity = _require_int_at_least(raw.get("quantity"), 1, f"{ctx}.quantity")
    tier_minimum = raw.get("tier_minimum")
    if isinstance(tier_minimum, bool) or not isinstance(tier_minimum, int) or tier_minimum not in _MATERIAL_TIERS:
        raise ValueError(f"{ctx}.tier_minimum {tier_minimum!r} is not 1-4")
    substitutable = raw.get("substitutable")
    if not isinstance(substitutable, bool):
        raise ValueError(f"{ctx}.substitutable is not a boolean")
    return {
        "material_id": material_id,
        "quantity": quantity,
        "tier_minimum": tier_minimum,
        "substitutable": substitutable,
    }


def parse_recipe_row(recipe_id: str, raw: object) -> dict:
    """Canonical fail-loud parser for one recipes-table row's `data` payload.

    Mirrors apps/server/src/recipes.ts parseRecipeRow: validates all 16 Recipe
    fields, raising ValueError with a `recipes[<id>].<field>` context on any
    mismatch. id comes from the row key (passed in), not the data. Validates a
    single recipe in isolation — material_id->catalog referential integrity is a
    cross-entity check owned by the TS content-validation test.

    Like the TS parser, narration_cues band keys are NOT enum-validated here
    (concern 31c6bd30ca97, deferred for both languages); only that the dict is
    non-empty with string values. The crafting-narration-bands decision records
    the canonical band vocabulary for future drift-catching.
    """
    ctx = f"recipes[{recipe_id}]"
    if not isinstance(raw, dict):
        raise ValueError(f"{ctx}.data is not an object")

    name = raw.get("name")
    if not isinstance(name, str):
        raise ValueError(f"{ctx}.name is not a string")
    category = raw.get("category")
    if not isinstance(category, str) or category not in _CATEGORIES:
        raise ValueError(f"{ctx}.category {category!r} is invalid")
    tier = raw.get("tier")
    if not isinstance(tier, str) or tier not in _TIERS:
        raise ValueError(f"{ctx}.tier {tier!r} is invalid")

    materials_raw = raw.get("materials")
    if not isinstance(materials_raw, list):
        raise ValueError(f"{ctx}.materials is not an array")
    materials = [_parse_material_req(m, f"{ctx}.materials[{i}]") for i, m in enumerate(materials_raw)]
    optional_raw = raw.get("optional_materials")
    if not isinstance(optional_raw, list):
        raise ValueError(f"{ctx}.optional_materials is not an array")
    optional_materials = [_parse_material_req(m, f"{ctx}.optional_materials[{i}]") for i, m in enumerate(optional_raw)]

    tainted_materials = raw.get("tainted_materials")
    if not isinstance(tainted_materials, bool):
        raise ValueError(f"{ctx}.tainted_materials is not a boolean")
    workspace = raw.get("workspace_required")
    if not isinstance(workspace, str) or workspace not in _WORKSPACES:
        raise ValueError(f"{ctx}.workspace_required {workspace!r} is invalid")

    crafting_dc = _require_int_at_least(raw.get("crafting_dc"), 1, f"{ctx}.crafting_dc")
    time = raw.get("time")
    if not isinstance(time, str):
        raise ValueError(f"{ctx}.time is not a string")
    async_cycles = _require_int_at_least(raw.get("async_cycles"), 0, f"{ctx}.async_cycles")
    output_item = raw.get("output_item")
    if not isinstance(output_item, str) or len(output_item) == 0:
        raise ValueError(f"{ctx}.output_item is not a non-empty string")
    output_quantity = _require_int_at_least(raw.get("output_quantity"), 1, f"{ctx}.output_quantity")
    study_cost = _require_int_at_least(raw.get("study_cost"), 0, f"{ctx}.study_cost")

    sources_raw = raw.get("discovery_sources")
    if not isinstance(sources_raw, list):
        raise ValueError(f"{ctx}.discovery_sources is not an array")
    discovery_sources = []
    for i, s in enumerate(sources_raw):
        if not isinstance(s, str):
            raise ValueError(f"{ctx}.discovery_sources[{i}] is not a string")
        discovery_sources.append(s)

    cues_raw = raw.get("narration_cues")
    if not isinstance(cues_raw, dict) or len(cues_raw) == 0:
        raise ValueError(f"{ctx}.narration_cues is not a non-empty object")
    narration_cues = {}
    for band, cue in cues_raw.items():
        if not isinstance(cue, str):
            raise ValueError(f"{ctx}.narration_cues[{band}] is not a string")
        narration_cues[band] = cue

    return {
        "id": recipe_id,
        "name": name,
        "category": category,
        "tier": tier,
        "materials": materials,
        "optional_materials": optional_materials,
        "tainted_materials": tainted_materials,
        "workspace_required": workspace,
        "crafting_dc": crafting_dc,
        "time": time,
        "async_cycles": async_cycles,
        "output_item": output_item,
        "output_quantity": output_quantity,
        "study_cost": study_cost,
        "discovery_sources": discovery_sources,
        "narration_cues": narration_cues,
    }


async def get_recipe(recipe_id: str) -> dict | None:
    """Return the parsed recipe for recipe_id, or None if unknown.

    Caches the PARSED dict (parse-once), an intentional departure from the raw
    json caching in db_content_queries — recipes are validated at the boundary,
    so the cache holds the already-validated shape. Round-trips cleanly through
    json since the parser emits only plain dict/list/str/int/bool.
    """
    cache_key = f"recipe:{recipe_id}"
    cached = await db._cache_get(cache_key)
    if cached is not None:
        return json.loads(cached)

    pool = await db.get_pool()
    row = await pool.fetchrow("SELECT data FROM recipes WHERE id = $1", recipe_id)
    if row is None:
        return None

    recipe = parse_recipe_row(recipe_id, json.loads(row["data"]))
    await db._cache_set(cache_key, json.dumps(recipe))
    return recipe


async def list_recipes() -> list[dict]:
    """Return all parsed recipes, cached under recipes:all."""
    cache_key = "recipes:all"
    cached = await db._cache_get(cache_key)
    if cached is not None:
        return json.loads(cached)

    pool = await db.get_pool()
    rows = await pool.fetch("SELECT id, data FROM recipes ORDER BY id")
    parsed = [parse_recipe_row(r["id"], json.loads(r["data"])) for r in rows]
    await db._cache_set(cache_key, json.dumps(parsed))
    return parsed
