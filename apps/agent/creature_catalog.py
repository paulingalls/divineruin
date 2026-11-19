"""Internal reads of the seeded creature catalog."""

import json
import re
from collections.abc import Iterable, Iterator

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


def _scene_bindings(value) -> Iterator[str]:
    if isinstance(value, str):
        yield from re.findall(r"encounter_id\s*=\s*[\"']([^\"']+)[\"']", value.replace('\\"', '"').replace("\\'", "'"))
    elif isinstance(value, dict):
        for child in value.values():
            yield from _scene_bindings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _scene_bindings(child)


def scene_encounter_ids(scenes: Iterable[dict]) -> set[str]:
    """Encounter template ids that scenes start by an `encounter_id="..."` string."""
    return {encounter_id for scene in scenes for encounter_id in _scene_bindings(scene)}


def scene_only_creature_ids(templates: dict[str, dict], scenes: Iterable[dict]) -> set[str]:
    """Creature ids whose every template is scene-bound; generated encounters must not spawn them."""
    bound = scene_encounter_ids(scenes)
    used = {tid: {enemy["creature_id"] for enemy in t["enemies"]} for tid, t in templates.items()}
    in_bound = set().union(*(ids for tid, ids in used.items() if tid in bound))
    elsewhere = set().union(*(ids for tid, ids in used.items() if tid not in bound))
    return in_bound - elsewhere


async def query_scene_only_creature_ids() -> set[str]:
    pool = await db.get_pool()
    templates = await pool.fetch("SELECT id, data FROM encounter_templates")
    scenes = await pool.fetch("SELECT data FROM scenes")
    return scene_only_creature_ids(
        {row["id"]: json.loads(row["data"]) for row in templates},
        (json.loads(row["data"]) for row in scenes),
    )


async def encounter_template_summaries(location: dict, level: int) -> list[dict]:
    from livekit.agents.llm import ToolError

    pool = await db.get_pool()
    templates = await pool.fetch("SELECT id, data FROM encounter_templates ORDER BY id")
    quests = await pool.fetch("SELECT data FROM quests")
    scenes = await pool.fetch("SELECT data FROM scenes")
    catalog = {row["id"]: json.loads(row["data"]) for row in await pool.fetch("SELECT id, data FROM creatures")}
    bound = {
        stage["completion_conditions"]["encounter"]
        for row in quests
        for stage in json.loads(row["data"])["stages"]
        if "encounter" in stage.get("completion_conditions", {})
    }

    bound |= scene_encounter_ids(json.loads(row["data"]) for row in scenes)
    summaries = []
    for row in templates:
        try:
            template = json.loads(row["data"])
            recommended = template["recommended_party_level"]
            if type(recommended) is not int or recommended < 1:
                raise ValueError("invalid recommended_party_level")
            species = [catalog[enemy["creature_id"]] for enemy in template["enemies"]]
            if not species:
                raise ValueError("no enemy species")
            for creature in species:
                for field in ("regions", "terrains"):
                    if not isinstance(creature[field], list) or not creature[field]:
                        raise ValueError(f"invalid {field} for {creature['id']}")
            description = re.split(r"(?<=[.!?])\s+", species[0]["narration"]["first_sighting"].strip())[0]
            difficulty = template["difficulty"]
            if not description or not isinstance(difficulty, str) or not difficulty:
                raise ValueError("missing description or difficulty")
            if row["id"] in bound or recommended > level:
                continue
            if not all(location["region"] in c["regions"] and location["terrain"] in c["terrains"] for c in species):
                continue
            summary = {"id": row["id"], "difficulty": difficulty, "description": description}
            if "recommended_party_size" in template:
                summary["recommended_party_size"] = template["recommended_party_size"]
            summaries.append(summary)
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise ToolError(f"Encounter template '{row['id']}' is invalid: {error}") from error
    return summaries


async def creature_summary(session, target_id):
    from livekit.agents.llm import ToolError

    import db_content_queries
    import db_queries
    from combat_entry import load_party_players, mean_player_level
    from creature_tiers import tier_for_player_level

    try:
        if target_id:
            rows = [await query_creature_by_id(target_id)]
        else:
            location = await db_content_queries.get_location(session.location_id)
            if location is None:
                raise ToolError(f"Location '{session.location_id}' not found.")
            player = await db_queries.get_player(session.acting_player_id)
            if player is None:
                raise ToolError(f"Player '{session.acting_player_id}' not found.")
            members = await load_party_players(session, player, queries=db_queries)
            level = mean_player_level(members)
            tier = tier_for_player_level(level)
            region = location.get("region")
            if not isinstance(region, str):
                raise ValueError(f"Location '{session.location_id}' has invalid region {region!r}")
            rows = await query_creatures_by_region(region, tier)
            if not isinstance(location.get("terrain"), str):
                raise ValueError(f"Location '{session.location_id}' has invalid terrain")
            templates = await encounter_template_summaries(location, level)
    except (CreatureNotFoundError, ValueError) as error:
        raise ToolError(f"Creature query failed: {error}") from error
    keys = (
        "id",
        "name",
        "category",
        "tier",
        "level",
        "hp",
        "ac",
        "speed",
        "attacks",
        "behavior",
        "narration",
        "audio",
        "hollow",
        "signature_ability",
    )
    summaries = [{key: row[key] for key in keys if key in row} for row in rows]
    return json.dumps(summaries[0] if target_id else {"creatures": summaries, "encounter_templates": templates})
