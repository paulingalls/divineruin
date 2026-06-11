"""Database read queries -- player state, NPC state, inventory, skills, quests, session.

All async, accept optional conn parameter.
"""

import asyncio
import json
import logging

import asyncpg

import db
import db_activity_queries
import db_content_queries
from workspace import WorkspaceType

logger = logging.getLogger("divineruin.db")


# --- State queries (not cached) ---


async def get_npc_disposition(
    npc_id: str,
    player_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
    for_update: bool = False,
) -> str | None:
    _conn = conn or await db.get_pool()
    sql = "SELECT data FROM npc_dispositions WHERE npc_id = $1 AND player_id = $2"
    if for_update:
        sql += " FOR UPDATE"
    row = await _conn.fetchrow(sql, npc_id, player_id)
    if row is None:
        return None
    data = json.loads(row["data"])
    return data.get("disposition")


async def get_player_faction_reputation(
    player_id: str,
    faction_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> int | None:
    """Return the player's int reputation with a faction, or None if no row (story-008).

    Reads player_reputation.data["value"] — this query forward-defines that shape; no
    writer ships yet, so a missing row (None) is the common case and the stance-gate caller
    defaults it to neutral. A read-only stance input, so no FOR UPDATE lock path.
    """
    _conn = conn or await db.get_pool()
    row = await _conn.fetchrow(
        "SELECT data FROM player_reputation WHERE player_id = $1 AND faction_id = $2",
        player_id,
        faction_id,
    )
    if row is None:
        return None
    data = json.loads(row["data"])
    return data.get("value")


async def get_companion_relationship(
    player_id: str,
    companion_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> dict | None:
    """Return companion relationship state, or None if no row (M6.4 / story-003).

    Returns {relationship_tier, session_count, affinity, session_memories}. relationship_tier is
    a denormalized cache for external readers; session_count + affinity are the authoritative
    HYBRID inputs and every agent-side consumer re-derives the rank via
    companion_relationship.effective_tier_rank rather than trusting the cached column. Written by
    db_mutations.upsert_companion_relationship; a missing row means a never-met companion.
    """
    _conn = conn or await db.get_pool()
    row = await _conn.fetchrow(
        """
        SELECT relationship_tier, session_count, affinity, session_memories
        FROM companion_relationships
        WHERE player_id = $1 AND companion_id = $2
        """,
        player_id,
        companion_id,
    )
    if row is None:
        return None
    memories = row["session_memories"]
    return {
        "relationship_tier": row["relationship_tier"],
        "session_count": row["session_count"],
        "affinity": row["affinity"],
        "session_memories": json.loads(memories) if isinstance(memories, str) else memories,
    }


async def get_npc_dispositions(
    npc_ids: list[str], player_id: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> dict[str, str]:
    """Batch-fetch dispositions for multiple NPCs. Returns {npc_id: disposition}."""
    if not npc_ids:
        return {}
    _conn = conn or await db.get_pool()
    rows = await _conn.fetch(
        "SELECT npc_id, data FROM npc_dispositions WHERE npc_id = ANY($1) AND player_id = $2",
        npc_ids,
        player_id,
    )
    return {row["npc_id"]: json.loads(row["data"]).get("disposition", "neutral") for row in rows}


async def get_player(
    player_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
    for_update: bool = False,
) -> dict | None:
    _conn = conn or await db.get_pool()
    sql = "SELECT data FROM players WHERE player_id = $1"
    if for_update:
        sql += " FOR UPDATE"
    row = await _conn.fetchrow(sql, player_id)
    if row is None:
        return None
    data = json.loads(row["data"])
    # Guard against double-encoded JSONB (stored as JSON string instead of object)
    if isinstance(data, str):
        logger.warning("Double-encoded player data for %s -- run data migration", player_id)
        data = json.loads(data)
    if not isinstance(data, dict):
        logger.warning("Player %s has non-dict data: %s", player_id, type(data).__name__)
        return None
    return data


async def get_npc_combat_stats(npc_id: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None) -> dict | None:
    _conn = conn or await db.get_pool()
    row = await _conn.fetchrow("SELECT data FROM npc_state WHERE npc_id = $1", npc_id)
    if row is None:
        return None
    return json.loads(row["data"])


async def get_npcs_at_location(
    location_id: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> list[dict]:
    _conn = conn or await db.get_pool()
    rows = await _conn.fetch(
        """
        SELECT id, data FROM npcs
        WHERE EXISTS (
            SELECT 1 FROM jsonb_each_text(data->'schedule') AS s(k, v)
            WHERE v = $1
        )
        """,
        location_id,
    )
    return [{"id": row["id"], **json.loads(row["data"])} for row in rows]


async def get_targets_at_location(
    location_id: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> list[dict]:
    _conn = conn or await db.get_pool()
    rows = await _conn.fetch(
        "SELECT npc_id, data FROM npc_state WHERE data->>'location' = $1",
        location_id,
    )
    return [{"npc_id": row["npc_id"], **json.loads(row["data"])} for row in rows]


async def get_player_inventory(player_id: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None) -> list[dict]:
    _conn = conn or await db.get_pool()
    rows = await _conn.fetch(
        """
        SELECT i.data AS item_data, pi.data AS slot_data
        FROM player_inventory pi
        JOIN items i ON i.id = pi.item_id
        WHERE pi.player_id = $1
        """,
        player_id,
    )
    results = []
    for row in rows:
        item = json.loads(row["item_data"])
        slot = json.loads(row["slot_data"])
        item["slot_info"] = slot
        image_url = db._compute_item_image_url(item)
        if image_url:
            item["image_url"] = image_url
        results.append(item)
    return results


async def get_skill_advancement(
    player_id: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> dict[str, dict]:
    """Fetch all skill advancement data for a player.

    Returns dict keyed by skill_id: {"tier": str, "use_counter": int, "narrative_moment_ready": bool}
    """
    _conn = conn or await db.get_pool()
    rows = await _conn.fetch(
        "SELECT skill_id, tier, use_counter, narrative_moment_ready FROM skill_advancement WHERE player_id = $1",
        player_id,
    )
    return {
        row["skill_id"]: {
            "tier": row["tier"],
            "use_counter": row["use_counter"],
            "narrative_moment_ready": row["narrative_moment_ready"],
        }
        for row in rows
    }


async def get_single_skill_advancement(
    player_id: str, skill: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> dict:
    """Fetch advancement data for a single skill. Returns {tier, use_counter, narrative_moment_ready} or defaults."""
    _conn = conn or await db.get_pool()
    row = await _conn.fetchrow(
        "SELECT tier, use_counter, narrative_moment_ready FROM skill_advancement WHERE player_id = $1 AND skill_id = $2",
        player_id,
        skill,
    )
    if row is None:
        return {"tier": "untrained", "use_counter": 0, "narrative_moment_ready": False}
    return {
        "tier": row["tier"],
        "use_counter": row["use_counter"],
        "narrative_moment_ready": row["narrative_moment_ready"],
    }


async def get_crafting_skill_counter(player_id: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None) -> int:
    """Read the player's hidden Crafting skill counter (story-006). Defaults to 0."""
    _conn = conn or await db.get_pool()
    counter = await _conn.fetchval(
        "SELECT counter FROM player_crafting_skill_counter WHERE player_id = $1",
        player_id,
    )
    return counter or 0


async def count_player_known_recipes(player_id: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None) -> int:
    """Count recipes a player knows — the slot-capacity input for _learn_recipe_impl."""
    _conn = conn or await db.get_pool()
    count = await _conn.fetchval("SELECT COUNT(*) FROM player_known_recipes WHERE player_id = $1", player_id)
    return count or 0


async def get_player_known_recipe_ids(
    player_id: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> set[str]:
    """The set of recipe_ids a player knows — the pre-flight Check 1 (Knowledge) input."""
    _conn = conn or await db.get_pool()
    rows = await _conn.fetch("SELECT recipe_id FROM player_known_recipes WHERE player_id = $1", player_id)
    return {row["recipe_id"] for row in rows}


async def get_player_materials(
    player_id: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None, for_update: bool = False
) -> dict[str, int]:
    """Return {material_id: quantity} for a player's inventory — the pre-flight Check 4
    + craft-consume input. Reads player_inventory DIRECTLY (mirrors the TS consume path
    activities.ts), NOT via get_player_inventory's items JOIN — that JOIN drops material
    rows whose item_id is a materials_catalog id with no items-table row."""
    _conn = conn or await db.get_pool()
    sql = "SELECT item_id, COALESCE((data->>'quantity')::int, 1) AS quantity FROM player_inventory WHERE player_id = $1"
    if for_update:
        sql += " FOR UPDATE"
    rows = await _conn.fetch(sql, player_id)
    return {row["item_id"]: row["quantity"] for row in rows}


async def get_accessible_workspaces(
    player_id: str,
    location_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
    has_portable_lab: bool = False,
) -> set[str]:
    """The workspace types a player can use at location_id right now — pre-flight Check 3.
    Always includes 'field' (the universal floor); adds each active (unexpired or standing)
    location-bound rental's workspace_type. Python mirror of the TS accessibleWorkspaceTier
    (apps/server/src/workspace.ts); converts via WorkspaceType to fail loud on a typo'd type.

    When has_portable_lab is True, grants Workshop + basic Laboratory ANYWHERE (NOT Forge),
    the Artificer Portable-Lab exception (ADR 0005), matching the TS twin's hasPortableLab
    branch. The caller reads lab ownership once and passes it here AND to the slot validator."""
    _conn = conn or await db.get_pool()
    rows = await _conn.fetch(
        """
        SELECT workspace_type FROM workspace_rentals
        WHERE player_id = $1
          AND location_id = $2
          AND (expires_at IS NULL OR expires_at > NOW())
        """,
        player_id,
        location_id,
    )
    accessible = {WorkspaceType.FIELD.value}
    for row in rows:
        accessible.add(WorkspaceType(row["workspace_type"]).value)
    if has_portable_lab:
        accessible.add(WorkspaceType.WORKSHOP.value)
        accessible.add(WorkspaceType.LABORATORY.value)
    return accessible


async def get_inventory_item(
    player_id: str,
    item_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
    for_update: bool = False,
) -> dict | None:
    _conn = conn or await db.get_pool()
    sql = "SELECT data FROM player_inventory WHERE player_id = $1 AND item_id = $2"
    if for_update:
        sql += " FOR UPDATE"
    row = await _conn.fetchrow(sql, player_id, item_id)
    if row is None:
        return None
    return json.loads(row["data"])


# --- Quest state ---


async def get_player_quest(
    player_id: str,
    quest_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
    for_update: bool = False,
) -> dict | None:
    _conn = conn or await db.get_pool()
    sql = "SELECT data FROM player_quests WHERE player_id = $1 AND quest_id = $2"
    if for_update:
        sql += " FOR UPDATE"
    row = await _conn.fetchrow(sql, player_id, quest_id)
    if row is None:
        return None
    return json.loads(row["data"])


async def get_active_player_quests(
    player_id: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> list[dict]:
    _conn = conn or await db.get_pool()
    rows = await _conn.fetch(
        """
        SELECT pq.quest_id, pq.data AS pq_data, q.data AS q_data
        FROM player_quests pq
        JOIN quests q ON q.id = pq.quest_id
        WHERE pq.player_id = $1
          AND COALESCE(pq.data->>'status', 'active') = 'active'
        """,
        player_id,
    )
    results = []
    for row in rows:
        pq = json.loads(row["pq_data"])
        quest = json.loads(row["q_data"])
        current_stage = pq.get("current_stage", 0)
        stages = quest.get("stages", [])
        results.append(
            {
                "quest_id": row["quest_id"],
                "quest_name": quest.get("name", row["quest_id"]),
                "current_stage": current_stage,
                "stages": stages,
                "scene_graph": quest.get("scene_graph", []),
            }
        )
    return results


async def get_player_flag(
    player_id: str,
    flag: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> bool:
    _conn = conn or await db.get_pool()
    row = await _conn.fetchrow(
        "SELECT data->'flags'->>$2 AS val FROM players WHERE player_id = $1",
        player_id,
        flag,
    )
    if row is None or row["val"] is None:
        return False
    return row["val"] == "true"


async def get_player_flag_value(
    player_id: str,
    flag: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> bool | str | int | None:
    _conn = conn or await db.get_pool()
    row = await _conn.fetchrow(
        "SELECT data->'flags'->$2 AS val FROM players WHERE player_id = $1",
        player_id,
        flag,
    )
    if row is None or row["val"] is None:
        return None
    return json.loads(row["val"])


async def _enrich_quests_with_scene_hints(quests: list[dict]) -> list[dict]:
    """Add 'hints' from scene beats to each quest's data for client display."""
    from scene_tools import _resolve_scene_from_graph

    scene_ids: list[str] = []
    for q in quests:
        for entry in q.get("scene_graph", []):
            sid = entry.get("scene_id")
            if sid and sid not in scene_ids:
                scene_ids.append(sid)
    if not scene_ids:
        return quests

    scene_cache = await db_content_queries.get_scenes_batch(scene_ids)
    for q in quests:
        scene = _resolve_scene_from_graph(scene_cache, q, q.get("current_stage", 0))
        hints: list[str] = []
        if scene:
            for beat in scene.get("beats", []):
                hints.extend(beat.get("companion_hints", []))
        q["hints"] = hints
    return quests


async def get_session_init_payload(player_id: str) -> dict:
    """Build the full session_init payload for a player."""
    # Fetch player first (need location_id), then parallelize the rest
    player = await get_player(player_id)
    location_id = player.get("location_id", "") if player else ""

    location, inventory, quests, map_progress = await asyncio.gather(
        db_content_queries.get_location(location_id) if location_id else asyncio.sleep(0),
        get_player_inventory(player_id),
        get_active_player_quests(player_id),
        db_activity_queries.get_player_map_progress(player_id),
    )

    # Enrich quests with scene beat hints for client display
    quests = await _enrich_quests_with_scene_hints(quests)

    # Build portraits dict
    portraits = db._build_portraits(player, location_id)

    return {
        "character": player,
        "location": location if location_id else None,
        "quests": quests,
        "inventory": inventory,
        "map_progress": map_progress,
        "world_state": {"time": "evening"},
        "portraits": portraits,
    }


async def get_last_session_summary(
    player_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> dict | None:
    """Return the most recent session summary for a player, or None."""
    _conn = conn or await db.get_pool()
    row = await _conn.fetchrow(
        """
        SELECT data FROM session_summaries
        WHERE player_id = $1
        ORDER BY created_at DESC
        LIMIT 1
        """,
        player_id,
    )
    if row is None:
        return None
    return json.loads(row["data"])
