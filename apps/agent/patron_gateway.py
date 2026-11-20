"""Beyond the Horizon moves the party and charges only the speaking follower."""

import asyncpg
from livekit.agents.llm import ToolError
from livekit.agents.voice import RunContext

import db
import db_activity_queries
import db_content_queries
import db_mutations_resonance
import db_queries
import still_charm
from region_types import REGION_CITY
from resonance_events import publish_resonance_changed
from session_data import SessionData

GATEWAY = "nythera_beyond_the_horizon"
RESONANCE_COST = 5


async def _visited(player_id: str, *, conn: asyncpg.Connection | None = None) -> set[str]:
    return {row["location_id"] for row in await db_activity_queries.get_player_map_progress(player_id, conn=conn)}


async def destinations(player_id: str, origin_id: str) -> list[dict[str, str]]:
    choices = []
    for location_id in sorted(await _visited(player_id) - {origin_id}):
        location = await db_content_queries.get_location(location_id)
        if location is None:
            raise ToolError(f"Visited location '{location_id}' no longer exists.")
        choices.append({"id": location_id, "name": location["name"]})
    return choices


async def activate(context: RunContext[SessionData], *, target_id: str | None) -> str | tuple:
    session = context.userdata
    async with session.combat_state_lock:
        return await activate_locked(context, session.acting_player_id, target_id=target_id)


async def activate_locked(context: RunContext[SessionData], actor: str, *, target_id: str | None) -> str | tuple:
    import movement_tools
    import quest_progress
    from patron_ability_events import publish_patron_abilities
    from patron_ability_tools import _locked_ability, _write_spend
    from scene_tools import _build_scene_context

    session = context.userdata
    origin_id = session.location_id
    party_ids = tuple(sorted(session.party.member_ids))
    async with db.transaction() as conn:
        session.validate_acting_player(actor)
        players = await still_charm.lock_players(party_ids, queries=db_queries, conn=conn)
        ability = await _locked_ability(conn, actor, GATEWAY)
        if session.in_combat:
            raise ToolError("Beyond the Horizon cannot open during combat.")
        if not target_id or not target_id.strip():
            raise ToolError("Choose a visited location with target_id.")
        if target_id == origin_id:
            raise ToolError("The gateway cannot open to your current location.")
        destination = await db_content_queries.get_location(target_id, conn=conn)
        if destination is None:
            raise ToolError(f"Unknown gateway destination '{target_id}'.")
        if target_id not in await _visited(actor, conn=conn):
            raise ToolError(f"You have never visited '{target_id}'.")
        origin = await db_content_queries.get_location(origin_id, conn=conn)
        if origin is None:
            raise ToolError(f"Current location '{origin_id}' not found.")
        still_charm.require_departure(players, target_id)
        await _write_spend(conn, session, actor, GATEWAY)
        apply = await movement_tools.write_arrival(session, target_id, destination, origin_id, party_ids, conn=conn)
        resonance = await db_mutations_resonance.read_player_resonance(actor, conn=conn)
        current = resonance["current"] + RESONANCE_COST
        await db_mutations_resonance.update_player_resonance(actor, current, conn=conn)

    publish_arrival = apply()
    await publish_arrival()
    track = session.member_state(actor).resonance
    track.current = current
    track.flickering_bonus = resonance["flickering_bonus"]
    await publish_resonance_changed(session, resonance_track=track, caster_id=actor)
    await publish_patron_abilities(session.room, actor, session.event_bus)
    quest_updates = await quest_progress.advance_on_arrival(context, target_id)
    session.record_event(f"Opened Beyond the Horizon to {target_id}")

    scene = await _build_scene_context(target_id, session, location=destination)
    return movement_tools.arrival_result(
        context,
        target_id,
        destination,
        origin.get("region_type", REGION_CITY),
        {
            "id": GATEWAY,
            "name": ability["name"],
            "recharge": ability["recharge"],
            "moved": True,
            "previous_location": origin_id,
            "quest_updates": quest_updates,
            **scene,
        },
    )
