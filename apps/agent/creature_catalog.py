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
            tier = tier_for_player_level(mean_player_level(members))
            region = location.get("region")
            if not isinstance(region, str):
                raise ValueError(f"Location '{session.location_id}' has invalid region {region!r}")
            rows = await query_creatures_by_region(region, tier)
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
    return json.dumps(summaries[0] if target_id else summaries)
