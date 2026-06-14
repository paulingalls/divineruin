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
from companion_profiles import get_companion_profile
from companion_scaling import (
    companion_attacks_to_action_pool,
    scale_companion_stats_to_player_level,
)
from encounter_stance import resolve_encounter_stance
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

    # Stance gate (story-008): a gated encounter resolves allied/hostile from the player's
    # reputation with the GATE faction. "allied" stands the encounter down (return a narration
    # string — no combat handoff); "hostile" falls through to the normal combat build. The
    # reputation defaults to neutral (0) when unset — no player_reputation writer ships yet
    # (debt 6e8c1e79a775), so gated encounters resolve hostile in prod until one does.
    stance_gate = encounter.get("stance_gate")
    if stance_gate is not None:
        faction_id = stance_gate.get("faction")
        if not faction_id:
            raise ToolError(f"Encounter '{encounter_id}' has a malformed stance gate: missing 'faction'.")
        faction = await content.get_faction(faction_id)
        if faction is None:
            raise ToolError(f"Stance-gate faction '{faction_id}' not found.")
        reputation = await queries.get_player_faction_reputation(session.player_id, faction_id)
        try:
            stance = resolve_encounter_stance(
                stance_gate,
                reputation if reputation is not None else 0,
                faction.get("reputation_tiers") or {},
            )
        except ValueError as e:
            raise ToolError(f"Encounter '{encounter_id}' has a malformed stance gate: {e}") from e
        if stance == "allied":
            session.record_event(f"{encounter.get('name', encounter_id)} stood down — allied")
            logger.info("start_combat: encounter %s resolved allied; combat averted", encounter_id)
            return f"The {faction.get('name', faction_id)} recognizes you as an ally and stands down. No combat."

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

    # Add companion if present and conscious. Stats come from the companions.json profile
    # (companion_scaling: level scaler + action_pool translator), NOT npcs.json — and they are
    # independent of relationship (session_count/affinity); combat is never relationship-gated
    # (spec L871, the negative invariant).
    companion_scaled = None
    companion_action_pool: list[dict] = []
    if session.companion_can_act and session.companion:
        try:
            profile = get_companion_profile(session.companion.id)
            # Both translators consume the profile and fail loud on a corrupt seed (an attack
            # whose damage/hit has no parseable term). Keep them inside the try so a catalog
            # inconsistency surfaces as a DM-narratable ToolError, just like an unknown id —
            # instead of a raw ValueError that crashes combat init.
            companion_scaled = scale_companion_stats_to_player_level(
                profile, player_hp.get("max", 1), player.get("level", 1)
            )
            companion_action_pool = companion_attacks_to_action_pool(profile)
        except ValueError as e:
            # Unknown/unloaded companion id (stale id) or a malformed profile attack. Surface as
            # a ToolError so the DM narrates cleanly — matching the encounter/player/faction
            # not-found convention above — instead of crashing combat init.
            raise ToolError(f"Companion '{session.companion.id}' not found: {e}") from e
        initiative_inputs.append(
            {
                "id": session.companion.id,
                "name": session.companion.name,
                "attributes": companion_scaled.attributes,
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
    if companion_scaled is not None and session.companion:
        participants.append(
            CombatParticipant(
                id=session.companion.id,
                name=session.companion.name,
                type="companion",
                initiative=initiative_by_id[session.companion.id],
                hp_current=companion_scaled.hp,
                hp_max=companion_scaled.hp,
                ac=companion_scaled.ac,
                attributes=companion_scaled.attributes,
                level=companion_scaled.level,
                action_pool=companion_action_pool,
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
    session.draethar_inner_fire_used = False  # Inner Fire is once per encounter (M3.4)

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
