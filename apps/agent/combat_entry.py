"""Party and source preparation for the locked combat entry path."""

from random import Random
from uuid import uuid4

from livekit.agents.llm import ToolError

import encounter_builder
from combat_spatial_entry import default_scene_placement
from combat_terrain import resolve_terrain
from companion_profiles import get_companion_profile
from creature_catalog import query_creatures_by_region
from creature_tiers import tier_for_player_level


def mean_player_level(member_players):
    return sum(row["level"] for _, row in member_players) // len(member_players)


def validate_entry_form(encounter_id, difficulty, tier):
    if encounter_id and (difficulty or tier is not None):
        raise ToolError("encounter_id and generated difficulty/tier are mutually exclusive.")
    if not encounter_id:
        if difficulty not in encounter_builder.ROUND_WINDOWS:
            raise ToolError("Generated combat requires difficulty standard, tough or boss (or use encounter_id).")
        if tier is not None and (type(tier) is not int or not 1 <= tier <= 4):
            raise ToolError("Generated combat tier must be 1-4.")


async def generated_encounter(session, member_players, difficulty, tier, *, content):
    location = await content.get_location(session.location_id)
    if location is None:
        raise ToolError(f"Location '{session.location_id}' not found.")
    terrain = await resolve_terrain(session, content_mod=content)
    level = mean_player_level(member_players)
    party = [{"id": mid, "type": "player", "level": row["level"]} for mid, row in member_players]
    try:
        if session.companion_can_act and session.companion:
            profile = get_companion_profile(session.companion.id)
            party.append(
                {
                    "id": profile.id,
                    "type": "companion",
                    "player_id": session.primary_player_id,
                    "hp_factor": profile.scaling_rules.hp_factor,
                }
            )
        catalog = await query_creatures_by_region(location.get("region"))
        references = encounter_builder.build_encounter(
            catalog,
            tier if tier is not None else tier_for_player_level(level),
            party,
            {"region": location.get("region"), "terrain": terrain},
            difficulty,
            Random(),
        )
    except ValueError as error:
        raise ToolError(str(error)) from error
    return {
        "id": f"generated_{uuid4().hex}",
        "name": "Generated encounter",
        "recommended_party_level": level,
        "enemies": references,
        "difficulty": "moderate" if difficulty == "standard" else "hard",
        "scene_placement": default_scene_placement(references),
    }, terrain


async def load_party_players(session, player, *, queries):
    actor_id = session.acting_player_id
    other_member_ids = [m for m in session.party.member_ids if m != actor_id]
    fetched = await queries.get_players_for_update(other_member_ids) if other_member_ids else {}
    member_players: list[tuple[str, dict]] = []
    for member_id in session.party.member_ids:
        row = player if member_id == actor_id else fetched.get(member_id)
        if row is None:
            raise ToolError(f"Player '{member_id}' not found.")
        member_players.append((member_id, row))

    return member_players
