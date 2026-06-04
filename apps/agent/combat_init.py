"""Combat initialization — _start_combat_impl, the combat-entry handoff behind
enter_mode(mode="combat") (mode_tools.py). Rolls initiative, persists CombatState,
and hands off to CombatAgent."""

import json
import logging
import uuid

from livekit.agents.llm import ToolError
from livekit.agents.voice import RunContext

import combat_resolution
import db_content_queries
import db_mutations
import db_queries
import event_types as E
from combat_support import _participant_summary, _publish_sounds
from game_events import publish_game_event
from region_types import REGION_CITY
from session_data import CombatParticipant, CombatState, SessionData
from tool_support import SOUND_COMBAT_START

logger = logging.getLogger("divineruin.tools")


async def _start_combat_impl(
    context: RunContext[SessionData],
    encounter_id: str,
    encounter_description: str,
    *,
    mutations=db_mutations,
    queries=db_queries,
    content=db_content_queries,
) -> str | tuple:
    logger.info("start_combat called: encounter_id=%s", encounter_id)
    session: SessionData = context.userdata

    if session.in_combat:
        raise ToolError("Already in combat. End the current combat first.")

    encounter = await content.get_encounter_template(encounter_id)
    if encounter is None:
        raise ToolError(f"Encounter template '{encounter_id}' not found.")

    player = await queries.get_player(session.player_id)
    if player is None:
        raise ToolError(f"Player '{session.player_id}' not found.")

    # Build participant dicts for initiative rolling
    player_hp = player.get("hp", {})
    player_attrs = player.get("attributes", {})
    initiative_inputs: list[dict] = [
        {
            "id": session.player_id,
            "name": player.get("name", session.player_id),
            "attributes": player_attrs,
        }
    ]

    enemies = encounter.get("enemies", [])
    for enemy in enemies:
        initiative_inputs.append(
            {
                "id": enemy["id"],
                "name": enemy.get("name", enemy["id"]),
                "attributes": enemy.get("attributes", {}),
            }
        )

    # Add companion if present and conscious
    companion_npc = None
    comp_stats: dict = {}
    comp_attrs: dict = {}
    if session.companion_can_act and session.companion:
        companion_npc = await content.get_npc(session.companion.id)
        if companion_npc:
            comp_stats = companion_npc.get("combat_stats", {})
            comp_attrs = comp_stats.get("attributes", {"strength": 12, "dexterity": 12})
            initiative_inputs.append(
                {
                    "id": session.companion.id,
                    "name": session.companion.name,
                    "attributes": comp_attrs,
                }
            )

    # Roll initiative and build lookup
    initiative_entries = combat_resolution.roll_initiative(initiative_inputs)
    initiative_order = [e.participant_id for e in initiative_entries]
    initiative_by_id = {e.participant_id: e.total for e in initiative_entries}

    # Build CombatParticipants
    participants: list[CombatParticipant] = [
        CombatParticipant(
            id=session.player_id,
            name=player.get("name", session.player_id),
            type="player",
            initiative=initiative_by_id[session.player_id],
            hp_current=player_hp.get("current", 1),
            hp_max=player_hp.get("max", 1),
            ac=player.get("ac", 10),
            attributes=player_attrs,
            level=player.get("level", 1),
        ),
    ]
    for enemy in enemies:
        participants.append(
            CombatParticipant(
                id=enemy["id"],
                name=enemy.get("name", enemy["id"]),
                type="enemy",
                initiative=initiative_by_id[enemy["id"]],
                hp_current=enemy.get("hp", 1),
                hp_max=enemy.get("hp", 1),
                ac=enemy.get("ac", 10),
                attributes=enemy.get("attributes", {}),
                level=enemy.get("level", 1),
                action_pool=enemy.get("action_pool", []),
                xp_value=enemy.get("xp_value", 0),
            )
        )

    # Add companion participant
    if companion_npc is not None and session.companion:
        participants.append(
            CombatParticipant(
                id=session.companion.id,
                name=session.companion.name,
                type="companion",
                initiative=initiative_by_id[session.companion.id],
                hp_current=comp_stats.get("hp", 20),
                hp_max=comp_stats.get("hp", 20),
                ac=comp_stats.get("ac", 14),
                attributes=comp_attrs,
                level=comp_stats.get("level", 2),
                action_pool=comp_stats.get("action_pool", []),
            )
        )

    combat_id = f"combat_{uuid.uuid4().hex[:8]}"
    combat_state = CombatState(
        combat_id=combat_id,
        participants=participants,
        initiative_order=initiative_order,
        round_number=1,
        current_turn_index=0,
        location_id=session.location_id,
    )

    # Persist and update session
    await mutations.save_combat_state(combat_id, combat_state.to_dict())
    session.combat_state = combat_state

    # Reset per-encounter weapon durability flags so each encounter is self-contained
    # (a swing outside combat won't leak into this encounter's end-of-combat accrual).
    session.weapon_used_this_encounter = False
    session.weapon_crit_vs_heavy = False

    # Build initiative summary once for event + response
    initiative_summary = [
        {"id": e.participant_id, "name": e.name, "roll": e.roll, "total": e.total} for e in initiative_entries
    ]

    # Publish events
    await publish_game_event(
        session.room,
        E.COMBAT_STARTED,
        {
            "combat_id": combat_id,
            "encounter_id": encounter_id,
            "difficulty": encounter.get("difficulty", "moderate"),
            "initiative_order": initiative_summary,
        },
        event_bus=session.event_bus,
    )
    await _publish_sounds(session, [SOUND_COMBAT_START])

    session.record_event(f"Combat started: {encounter.get('name', encounter_id)}")

    response = {
        "combat_id": combat_id,
        "encounter_name": encounter.get("name", encounter_id),
        "encounter_description": encounter_description,
        "initiative_order": initiative_summary,
        "participants": [_participant_summary(p) for p in participants],
    }
    logger.info("start_combat result: combat_id=%s, %d participants", combat_id, len(participants))

    # Record which agent type to return to after combat
    current_agent = context.session.current_agent
    session.pre_combat_agent_type = getattr(current_agent, "_agent_type", REGION_CITY)

    # Build CombatAgent with combat-entry context for handoff
    from livekit.agents.llm import ChatContext

    from combat_agent import create_combat_agent

    parts = [f"Combat begins: {encounter_description}"]
    loc_name = getattr(session, "cached_location_name", None) or session.location_id
    parts.append(f"Location: {loc_name}.")
    if session.companion and session.companion.is_present:
        parts.append(f"{session.companion.name} fights alongside the player.")

    combat_ctx = ChatContext()
    combat_ctx.add_message(role="system", content=" ".join(parts))

    return create_combat_agent(chat_ctx=combat_ctx), json.dumps(response)
