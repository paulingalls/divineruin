"""Cached content lookup queries (locations, NPCs, items, lore, quests, scenes, encounters, training programs, errand templates).

All functions use db._cache_get() / db._cache_set() for Redis caching.
No conn parameter — these read from the pool and cache layer.
"""

import json
import logging

import db

logger = logging.getLogger("divineruin.db")


async def get_location(location_id: str) -> dict | None:
    cache_key = f"location:{location_id}"
    cached = await db._cache_get(cache_key)
    if cached is not None:
        return json.loads(cached)

    pool = await db.get_pool()
    row = await pool.fetchrow("SELECT data FROM locations WHERE id = $1", location_id)
    if row is None:
        return None

    data = json.loads(row["data"])
    await db._cache_set(cache_key, json.dumps(data))
    return data


async def get_all_locations() -> dict[str, dict]:
    """Return every location keyed by id ({id: data}). Used by the resurrection anchor resolver
    (M4.4) which needs the catalog to find same-region settlements + the starter zone. Cache-backed
    as a single blob; locations are static content so a whole-catalog read is cheap and rare."""
    cache_key = "locations:all"
    cached = await db._cache_get(cache_key)
    if cached is not None:
        return json.loads(cached)

    pool = await db.get_pool()
    rows = await pool.fetch("SELECT id, data FROM locations")
    out = {row["id"]: json.loads(row["data"]) for row in rows}
    await db._cache_set(cache_key, json.dumps(out))
    return out


async def get_faction(faction_id: str) -> dict | None:
    """Return a faction's content row (incl. reputation_tiers), or None if not found.

    Cache-backed read of the factions table — the stance-gate read seam (story-008):
    combat_init resolves an encounter's stance from the gate faction's reputation_tiers.
    """
    cache_key = f"faction:{faction_id}"
    cached = await db._cache_get(cache_key)
    if cached is not None:
        return json.loads(cached)

    pool = await db.get_pool()
    row = await pool.fetchrow("SELECT data FROM factions WHERE id = $1", faction_id)
    if row is None:
        return None

    data = json.loads(row["data"])
    await db._cache_set(cache_key, json.dumps(data))
    return data


async def get_location_region_type(location_id: str) -> str:
    """Return the region_type for a location ('city', 'wilderness', or 'dungeon').

    Falls back to 'city' if the location is not found or has no region_type.
    """
    from region_types import REGION_CITY

    location = await get_location(location_id)
    if location is None:
        return REGION_CITY
    return location.get("region_type", REGION_CITY)


async def get_npc(npc_id: str) -> dict | None:
    cache_key = f"npc:{npc_id}"
    cached = await db._cache_get(cache_key)
    if cached is not None:
        return json.loads(cached)

    pool = await db.get_pool()
    row = await pool.fetchrow("SELECT data FROM npcs WHERE id = $1", npc_id)
    if row is None:
        return None

    data = json.loads(row["data"])
    await db._cache_set(cache_key, json.dumps(data))
    return data


async def get_item(item_id: str) -> dict | None:
    cache_key = f"item:{item_id}"
    cached = await db._cache_get(cache_key)
    if cached is not None:
        return json.loads(cached)

    pool = await db.get_pool()
    row = await pool.fetchrow("SELECT data FROM items WHERE id = $1", item_id)
    if row is None:
        return None

    data = json.loads(row["data"])
    await db._cache_set(cache_key, json.dumps(data))
    return data


async def search_lore(keyword: str, limit: int = 5) -> list[dict]:
    keyword = keyword[:256]
    # Escape ILIKE metacharacters
    escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    limit = max(1, min(limit, 100))
    pool = await db.get_pool()
    rows = await pool.fetch(
        "SELECT data FROM lore_entries WHERE data::text ILIKE $1 LIMIT $2",
        f"%{escaped}%",
        limit,
    )
    return [json.loads(row["data"]) for row in rows]


async def get_quest(quest_id: str) -> dict | None:
    cache_key = f"quest:{quest_id}"
    cached = await db._cache_get(cache_key)
    if cached is not None:
        return json.loads(cached)

    pool = await db.get_pool()
    row = await pool.fetchrow("SELECT data FROM quests WHERE id = $1", quest_id)
    if row is None:
        return None

    data = json.loads(row["data"])
    await db._cache_set(cache_key, json.dumps(data))
    return data


async def get_scene(scene_id: str) -> dict | None:
    cache_key = f"scene:{scene_id}"
    cached = await db._cache_get(cache_key)
    if cached is not None:
        return json.loads(cached)

    pool = await db.get_pool()
    row = await pool.fetchrow("SELECT data FROM scenes WHERE id = $1", scene_id)
    if row is None:
        return None

    data = json.loads(row["data"])
    await db._cache_set(cache_key, json.dumps(data))
    return data


async def get_scenes_batch(scene_ids: list[str]) -> dict[str, dict]:
    """Fetch multiple scenes by ID, returning a dict mapping scene_id -> scene data."""
    if not scene_ids:
        return {}
    # Check cache first for each id, collect misses
    result: dict[str, dict] = {}
    missing: list[str] = []
    for sid in scene_ids:
        cached = await db._cache_get(f"scene:{sid}")
        if cached is not None:
            result[sid] = json.loads(cached)
        else:
            missing.append(sid)
    # Batch-fetch misses with single query (mirrors get_npc_dispositions pattern)
    if missing:
        pool = await db.get_pool()
        rows = await pool.fetch("SELECT id, data FROM scenes WHERE id = ANY($1)", missing)
        for row in rows:
            data = json.loads(row["data"])
            result[row["id"]] = data
            await db._cache_set(f"scene:{row['id']}", json.dumps(data))
    return result


async def get_encounter_template(encounter_id: str) -> dict | None:
    cache_key = f"encounter:{encounter_id}"
    cached = await db._cache_get(cache_key)
    if cached is not None:
        return json.loads(cached)

    pool = await db.get_pool()
    row = await pool.fetchrow("SELECT data FROM encounter_templates WHERE id = $1", encounter_id)
    if row is None:
        return None

    data = json.loads(row["data"])
    await db._cache_set(cache_key, json.dumps(data))
    return data


async def get_loot_table(loot_table_id: str) -> dict | None:
    """Resolve a loot table by id from the loot_tables catalog (M4.7 story-002).

    Static content read from the pool + Redis cache (no conn param), mirroring
    get_encounter_template. combat_end calls this on victory — inside its teardown tx — to
    scale the table's base drops by each defeated enemy's role (encounter_loot.derive_role_loot).
    Reading from the pool rather than the in-flight tx conn is correct: loot tables are immutable
    seeded content, independent of the combat-teardown mutations. Returns None for an unknown id."""
    cache_key = f"loot_table:{loot_table_id}"
    cached = await db._cache_get(cache_key)
    if cached is not None:
        return json.loads(cached)

    pool = await db.get_pool()
    row = await pool.fetchrow("SELECT data FROM loot_tables WHERE id = $1", loot_table_id)
    if row is None:
        return None

    data = json.loads(row["data"])
    await db._cache_set(cache_key, json.dumps(data))
    return data


async def get_training_program(program_id: str) -> dict | None:
    cache_key = f"training_program:{program_id}"
    cached = await db._cache_get(cache_key)
    if cached is not None:
        return json.loads(cached)

    pool = await db.get_pool()
    row = await pool.fetchrow("SELECT data FROM training_programs WHERE id = $1", program_id)
    if row is None:
        return None

    data = json.loads(row["data"])
    await db._cache_set(cache_key, json.dumps(data))
    return data


async def list_training_programs() -> list[dict]:
    cache_key = "training_programs:all"
    cached = await db._cache_get(cache_key)
    if cached is not None:
        return json.loads(cached)

    pool = await db.get_pool()
    rows = await pool.fetch("SELECT data FROM training_programs ORDER BY id")
    programs = [json.loads(r["data"]) for r in rows]
    await db._cache_set(cache_key, json.dumps(programs))
    return programs


async def get_errand_template(errand_type: str) -> dict | None:
    cache_key = f"errand_template:{errand_type}"
    cached = await db._cache_get(cache_key)
    if cached is not None:
        return json.loads(cached)

    pool = await db.get_pool()
    row = await pool.fetchrow("SELECT data FROM errand_templates WHERE id = $1", errand_type)
    if row is None:
        return None

    data = json.loads(row["data"])
    await db._cache_set(cache_key, json.dumps(data))
    return data


async def list_errand_templates() -> list[dict]:
    cache_key = "errand_templates:all"
    cached = await db._cache_get(cache_key)
    if cached is not None:
        return json.loads(cached)

    pool = await db.get_pool()
    rows = await pool.fetch("SELECT data FROM errand_templates ORDER BY id")
    templates = [json.loads(r["data"]) for r in rows]
    await db._cache_set(cache_key, json.dumps(templates))
    return templates
