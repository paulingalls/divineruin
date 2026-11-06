"""Combat initialization — the locked combat-entry handoff behind enter_mode(mode="combat").

The session lock precedes the in-combat gate, content reads, persistence, and state adoption, so
concurrent starts cannot create two rows. Successful entry hands off to CombatAgent.
"""

import json
import logging
import uuid

from livekit.agents.llm import ToolError
from livekit.agents.voice import RunContext

import choir_scene
import combat_resolution as combat_resolution
import combat_spatial
import db
import db_content_queries
import db_mutations
import db_queries
import event_types as E
from combat_entry import generated_encounter, load_party_players, validate_entry_form
from combat_init_participants import assemble_participants
from combat_init_participants import class_reaction_ids as class_reaction_ids
from combat_init_validation import validate_enemy_action_shapes as validate_enemy_action_shapes
from combat_init_validation import validate_enemy_resistance_tags as validate_enemy_resistance_tags
from combat_support import _participant_roster, _publish_sounds
from combat_ui_update import build_combat_ui_update
from encounter_references import validate_encounter_references
from encounter_stance import resolve_encounter_stance
from game_events import publish_game_event
from region_types import REGION_CITY
from session_data import CombatState, SessionData
from tool_support import SOUND_COMBAT_START

logger = logging.getLogger("divineruin.tools")


async def _start_combat_impl(
    context: RunContext[SessionData],
    encounter_id: str,
    encounter_description: str,
    *,
    difficulty: str = "",
    tier: int | None = None,
    mutations=db_mutations,
    queries=db_queries,
    content=db_content_queries,
    db_mod=db,
) -> str | tuple:
    session: SessionData = context.userdata
    async with session.combat_state_lock:
        return await _start_combat_locked(
            context,
            encounter_id,
            encounter_description,
            difficulty=difficulty,
            tier=tier,
            mutations=mutations,
            queries=queries,
            content=content,
            db_mod=db_mod,
        )


async def _start_combat_locked(
    context: RunContext[SessionData],
    encounter_id: str,
    encounter_description: str,
    *,
    difficulty: str = "",
    tier: int | None = None,
    mutations=db_mutations,
    queries=db_queries,
    content=db_content_queries,
    db_mod=db,
) -> str | tuple:
    logger.info("start_combat called: encounter_id=%s", encounter_id)
    session: SessionData = context.userdata
    actor_id = session.acting_player_id

    if session.in_combat:
        raise ToolError("Already in combat. End the current combat first.")

    validate_entry_form(encounter_id, difficulty, tier)
    terrain = None
    member_players = None
    if encounter_id:
        encounter = await content.get_encounter_template(encounter_id)
        if encounter is None:
            raise ToolError(f"Encounter template '{encounter_id}' not found.")
    else:
        player = await queries.get_player(actor_id)
        if player is None:
            raise ToolError(f"Player '{actor_id}' not found.")
        member_players = await load_party_players(session, player, queries=queries)
        encounter, terrain = await generated_encounter(session, member_players, difficulty, tier, content=content)
        encounter_id = encounter["id"]

    try:
        validate_encounter_references(encounter)
        combat_spatial.validate_scene(encounter)
    except ValueError as error:
        raise ToolError(str(error)) from error

    if member_players is None:
        player = await queries.get_player(actor_id)
        if player is None:
            raise ToolError(f"Player '{actor_id}' not found.")
    else:
        player = dict(member_players)[actor_id]

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
        reputation = await queries.get_player_faction_reputation(actor_id, faction_id)
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

    if member_players is None:
        member_players = await load_party_players(session, player, queries=queries)

    participants, spatial, initiative_entries, initiative_order, retained_choir = await assemble_participants(
        session, encounter, encounter_id, member_players, content=content, queries=queries
    )

    # Carry the encounter's faction onto CombatState so combat_end can attribute the outcome
    # to faction reputation (story-002 inc 5). An explicit encounter `faction` wins; otherwise
    # the stance_gate faction (a gated encounter reaching combat resolved hostile). None when
    # the encounter has no faction — no reputation shift on such a fight.
    combat_faction_id = encounter.get("faction")
    if combat_faction_id is None and stance_gate is not None:
        combat_faction_id = stance_gate.get("faction")

    from combat_recharge import initialize

    for participant in participants:
        initialize(participant)

    from combat_terrain import resolve_terrain

    if terrain is None:
        terrain = await resolve_terrain(session, content_mod=content)
    combat_id = f"combat_{uuid.uuid4().hex[:8]}"
    combat_state = CombatState(
        encounter_id=encounter_id,
        combat_id=combat_id,
        participants=participants,
        initiative_order=initiative_order,
        round_number=1,
        current_turn_index=0,
        location_id=session.location_id,
        terrain=terrain,
        faction_id=combat_faction_id,
        spatial=spatial,
    )

    # Persist and update session
    session.validate_acting_player(actor_id)
    from choir_effects import exposure

    exposure(combat_state)
    import choir_encounter

    choir_encounter.initialize(combat_state)
    await choir_scene.start(session, combat_state, retained_choir, mutations=mutations, queries=queries, db_mod=db_mod)
    session.combat_state = combat_state

    # Reset per-encounter weapon durability flags so each encounter is self-contained
    # (a swing outside combat won't leak into this encounter's end-of-combat accrual). M18
    # story-003: every party member's own flags reset, so no member's prior-encounter swing leaks.
    for member in session.party.members:
        member.weapon_used = False
        member.weapon_crit_vs_heavy = False
        member.draethar_inner_fire_used = False

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
    # Initial HUD push so the combat-tracker has live combatants from round 1
    # (M12 sprint-029 close fix, concern 4045481bfc3e). Without this the
    # producer only fires at Beat-4 wrap, leaving the tracker empty for all of
    # round 1. Direct publish (no in-tx sink here); ordered AFTER COMBAT_STARTED
    # so the mobile session.setCombat(true) gate latches before render.
    await publish_game_event(
        session.room,
        E.COMBAT_UI_UPDATE,
        build_combat_ui_update(combat_state),
        event_bus=session.event_bus,
    )
    await _publish_sounds(session, [SOUND_COMBAT_START])

    session.record_event(f"Combat started: {encounter.get('name', encounter_id)}")

    response = {
        "choir": choir_encounter.facts(combat_state),
        "spatial": combat_spatial.facts(combat_state, actor_id),
        "combat_id": combat_id,
        "encounter_name": encounter.get("name", encounter_id),
        "encounter_description": encounter_description,
        "initiative_order": initiative_summary,
        "participants": _participant_roster(participants),
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
        from companion_prompts import companion_voice_directive

        parts.append(f"{session.companion.name} fights alongside the player.")
        parts.append(companion_voice_directive(session.companion))
    # The handoff drops start_combat's tool output from CombatAgent's context, so the roster rides here.
    parts.append(f"Combatants: {json.dumps(response['participants'])}")

    parts.append(f"Choir encounter: {json.dumps(response['choir'])}")
    parts.append(f"Spatial facts: {json.dumps(response['spatial'])}")

    combat_ctx = ChatContext()
    combat_ctx.add_message(role="system", content=" ".join(parts))

    return create_combat_agent(chat_ctx=combat_ctx), json.dumps(response)
