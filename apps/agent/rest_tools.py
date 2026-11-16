"""Safe, atomic party recovery through the exploration rest verb."""

import json

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import ability_persistence
import db
import db_content_queries
import db_mutations
import db_queries
import db_session_queries
import event_types as E
from archetypes import get_archetype_chassis
from db_errors import db_tool
from game_events import publish_game_event
from resonance_events import publish_resonance_changed
from rest_mechanics import RestType, apply_rest, record_last_rested_settlement, reset_resonance_on_rest
from session_data import SessionData


def _pool_values(player: dict, key: str) -> tuple[int, int]:
    pool = player.get(key)
    if not isinstance(pool, dict) or any(type(pool.get(k)) is not int for k in ("current", "max")):
        raise ValueError(f"Rest requires integer {key}.current and {key}.max")
    return pool["current"], pool["max"]


@function_tool()
@db_tool
async def rest(context: RunContext[SessionData], rest_type: RestType) -> str:
    """Rest when players choose recovery at a safe inn or tavern; narrate the returned
    recovery or refusal. short: Stamina refills and Focus recovers to half; HP does not.
    long: HP, Stamina and Focus refill and the settlement becomes the party's anchor.
    Rest is unavailable during combat or outside a safe rest location. Present,
    co-located party members recover together.
    """
    session = context.userdata
    actor = session.acting_player_id
    owner = session.multiplayer_owner
    member_ids = sorted(pid for pid in session.party.member_ids if owner.lifecycle.is_live(pid)) if owner else [actor]
    if actor not in member_ids:
        raise ToolError("You must be present to rest.")
    async with session.combat_state_lock:
        if session.in_combat:
            raise ToolError("You cannot rest during combat.")
        location_id = session.location_id
        location = await db_content_queries.get_location(location_id)
        if location is None:
            raise ValueError(f"Rest location {location_id!r} is missing")
        if "rest" not in location.get("tags", []):
            raise ToolError("This location has no place to rest.")
        if not location.get("settlement_tier"):
            raise ToolError("Rest requires an inn or tavern in a settlement.")
        if "danger_level" in location and location["danger_level"] != 0:
            raise ToolError("It is too dangerous to rest here.")
        anchor = None
        async with db.transaction() as conn:
            players = await db_queries.get_players_for_update(member_ids, conn=conn)
            if set(players) != set(member_ids):
                raise ValueError(f"Rest is missing player rows: {set(member_ids) - set(players)}")
            if players[actor].get("location_id") != location_id:
                raise ToolError("You are no longer at this rest location.")
            players = {pid: row for pid, row in players.items() if row.get("location_id") == location_id}
            recovery = {}
            for pid, row in players.items():
                current_hp, base_max_hp = _pool_values(row, "hp")
                hp = (current_hp, max(1, base_max_hp + row.get("maxhp_override", 0)))
                resource = get_archetype_chassis(row["class"]).resource
                stamina = _pool_values(row, "stamina") if "stamina" in row or resource.stamina_formula else None
                focus = _pool_values(row, "focus") if "focus" in row or resource.focus_formula else None
                recovery[pid] = apply_rest(rest_type, *(stamina or (None, None)), *(focus or (None, None)), *hp)
            session.validate_acting_player(actor)
            if rest_type == "long":
                anchor = await record_last_rested_settlement(list(players), location_id, conn=conn)
            for pid, (stamina, focus, hp) in recovery.items():
                session.validate_acting_player(actor)
                if hp != players[pid]["hp"]["current"]:
                    await db_mutations.update_player_hp(pid, hp, conn=conn)
                await ability_persistence.update_player_resources(pid, stamina=stamina, focus=focus, conn=conn)
                await reset_resonance_on_rest(pid, conn=conn)
        for pid in players:
            session.member_state(pid).resonance.current = 0
        for pid in players:
            payload = await db_session_queries.get_session_init_payload(pid)
            payload["character"]["player_id"] = pid
            payload["world_state"]["time"] = session.world_time
            await publish_game_event(
                session.room, E.SESSION_INIT, payload, session.event_bus, destination_identities=[pid]
            )
            await publish_resonance_changed(session, resonance_track=session.member_state(pid).resonance, caster_id=pid)
        return json.dumps(
            {
                "rested": True,
                "rest_type": rest_type,
                "location_id": location_id,
                "players": list(players),
                "settlement_id": anchor,
            }
        )
