"""Combat lifecycle tools for the DM agent."""

import json
import logging
import uuid

from livekit.agents.llm import function_tool
from livekit.agents.voice import RunContext

import check_resolution
import combat_resolution
import db_content_queries
import db_mutations
import db_queries
import event_types as E
from db_errors import db_tool
from game_events import publish_game_event
from region_types import REGION_CITY
from session_data import CombatParticipant, CombatState, SessionData
from tools import (
    SOUND_ATTACK_CRITICAL,
    SOUND_ATTACK_HIT,
    SOUND_ATTACK_MISS,
    SOUND_COMBAT_DEFEAT,
    SOUND_COMBAT_FLED,
    SOUND_COMBAT_START,
    SOUND_COMBAT_VICTORY,
    SOUND_DEATH_SAVE_CRITICAL,
    SOUND_DEATH_SAVE_FAIL,
    SOUND_DEATH_SAVE_SUCCESS,
    SOUND_HEARTBEAT,
    SOUND_PLAYER_DEATH,
    SOUND_PLAYER_FALLEN,
    SOUND_PLAYER_STABILIZED,
)

logger = logging.getLogger("divineruin.tools")


def _participant_summary(p: CombatParticipant) -> dict:
    """Serialize a participant for LLM response (no internal state like HP numbers)."""
    return {
        "id": p.id,
        "name": p.name,
        "type": p.type,
        "initiative": p.initiative,
        "hp_status": combat_resolution.hp_threshold_status(p.hp_current, p.hp_max),
        "ac": p.ac,
        "is_fallen": p.is_fallen,
    }


def _require_combat(session: SessionData) -> tuple[CombatState, str | None]:
    """Return (combat_state, None) if in combat, or (None, error_json) if not."""
    if session.combat_state is None:
        return None, json.dumps({"error": "Not in combat."})  # type: ignore[return-value]
    return session.combat_state, None


async def _publish_sounds(session: SessionData, sounds: list[str]) -> None:
    """Publish multiple sound events."""
    for sound in sounds:
        await publish_game_event(
            session.room,
            E.PLAY_SOUND,
            {"sound_name": sound},
            event_bus=session.event_bus,
        )


@function_tool()
@db_tool
async def start_combat(
    context: RunContext[SessionData],
    encounter_id: str,
    encounter_description: str,
) -> str | tuple:
    """Start combat using an encounter template. Rolls initiative for all
    participants and establishes turn order. Call this when combat begins.
    Provide the encounter template ID and a brief description of how
    combat starts."""
    logger.info("start_combat called: encounter_id=%s", encounter_id)
    session: SessionData = context.userdata

    if session.in_combat:
        return json.dumps({"error": "Already in combat. End the current combat first."})

    encounter = await db_content_queries.get_encounter_template(encounter_id)
    if encounter is None:
        return json.dumps({"error": f"Encounter template '{encounter_id}' not found."})

    player = await db_queries.get_player(session.player_id)
    if player is None:
        return json.dumps({"error": f"Player '{session.player_id}' not found."})

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
        companion_npc = await db_content_queries.get_npc(session.companion.id)
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
    await db_mutations.save_combat_state(combat_id, combat_state.to_dict())
    session.combat_state = combat_state

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


@function_tool()
@db_tool
async def resolve_enemy_turn(
    context: RunContext[SessionData],
    enemy_id: str,
    action_name: str,
    target_id: str,
) -> str:
    """Resolve an enemy's attack against a target during combat. Provide the
    enemy's participant ID, which action from their action_pool to use, and
    the target's participant ID. Narrate the result dramatically."""
    logger.info("resolve_enemy_turn called: enemy=%s, action=%s, target=%s", enemy_id, action_name, target_id)
    session: SessionData = context.userdata

    cs, err = _require_combat(session)
    if err:
        return err

    enemy = cs.get_participant(enemy_id)
    if enemy is None:
        return json.dumps({"error": f"Enemy '{enemy_id}' not found in combat."})
    if enemy.type not in ("enemy", "companion"):
        return json.dumps({"error": f"'{enemy_id}' is not an enemy or companion."})
    if enemy.is_fallen:
        return json.dumps({"error": f"'{enemy.name}' has fallen and cannot act."})

    # Find action
    action = None
    for a in enemy.action_pool:
        if a.get("name", "").lower() == action_name.lower():
            action = a
            break
    if action is None:
        available = [a.get("name") for a in enemy.action_pool]
        return json.dumps({"error": f"Action '{action_name}' not found. Available: {available}"})

    target = cs.get_participant(target_id)
    if target is None:
        return json.dumps({"error": f"Target '{target_id}' not found in combat."})
    if target.is_fallen:
        return json.dumps({"error": f"Target '{target.name}' has already fallen."})

    # Build attacker data from participant's stored attributes
    attacker_data = {
        "attributes": enemy.attributes,
        "level": enemy.level,
    }

    attack_result = check_resolution.resolve_attack(
        attacker_data,
        action,
        target.ac,
        target.hp_current,
    )

    # Update target HP
    target.hp_current = attack_result.target_hp_remaining

    # Determine sounds
    sounds: list[str] = []
    if attack_result.critical:
        sounds.append(SOUND_ATTACK_CRITICAL)
    elif attack_result.hit:
        sounds.append(SOUND_ATTACK_HIT)
    else:
        sounds.append(SOUND_ATTACK_MISS)

    # Check HP thresholds
    hp_status = combat_resolution.hp_threshold_status(target.hp_current, target.hp_max)
    if target.hp_current <= 0:
        target.is_fallen = True
        sounds.append(SOUND_PLAYER_FALLEN)
        # Handle companion KO
        if target.type == "companion" and session.companion and target.id == session.companion.id:
            session.companion.is_conscious = False
            session.record_companion_memory("Kael was knocked unconscious in combat")
    elif hp_status in ("bloodied", "critical"):
        sounds.append(SOUND_HEARTBEAT)

    # Update DB if target is a player
    if target.type == "player":
        await db_mutations.update_player_hp(target.id, target.hp_current)

    # Persist combat state
    await db_mutations.save_combat_state(cs.combat_id, cs.to_dict())

    # Publish events
    await publish_game_event(
        session.room,
        E.DICE_ROLL,
        {
            "roll_type": "attack",
            "attacker": enemy.name,
            "hit": attack_result.hit,
            "roll": attack_result.roll,
            "damage": attack_result.damage,
            "critical": attack_result.critical,
        },
        event_bus=session.event_bus,
    )
    await _publish_sounds(session, sounds)

    hit_miss = "hit" if attack_result.hit else "miss"
    session.record_event(f"{enemy.name} attacks {target.name}: {hit_miss}, {attack_result.damage} damage")

    response = {
        "attacker": enemy.name,
        "action": action_name,
        "target": target.name,
        "hit": attack_result.hit,
        "roll": attack_result.roll,
        "attack_total": attack_result.attack_total,
        "target_ac": target.ac,
        "damage": attack_result.damage,
        "damage_type": attack_result.damage_type,
        "critical": attack_result.critical,
        "target_hp_status": hp_status,
        "target_fallen": target.is_fallen,
        "narrative_hint": attack_result.narrative_hint,
    }
    logger.info(
        "resolve_enemy_turn result: %s → %s, %s, damage=%d, hp_status=%s",
        enemy.name,
        target.name,
        hit_miss,
        attack_result.damage,
        hp_status,
    )
    return json.dumps(response)


@function_tool()
@db_tool
async def request_death_save(
    context: RunContext[SessionData],
) -> str:
    """Roll a death saving throw for the fallen player. Call this when the
    player is at 0 HP and it's their turn (or when prompted). Nat 20 restores
    1 HP. Three successes stabilize, three failures mean death."""
    logger.info("request_death_save called")
    session: SessionData = context.userdata

    cs, err = _require_combat(session)
    if err:
        return err

    player_participant = cs.get_participant(session.player_id)
    if player_participant is None:
        return json.dumps({"error": "Player not found in combat."})
    if not player_participant.is_fallen:
        return json.dumps({"error": "Player has not fallen. Death saves only apply at 0 HP."})

    result = combat_resolution.resolve_death_save(
        player_participant.death_save_successes,
        player_participant.death_save_failures,
    )

    # Update participant state
    player_participant.death_save_successes = result.total_successes
    player_participant.death_save_failures = result.total_failures

    sounds: list[str] = []

    if result.critical_success:
        # Nat 20: regain 1 HP, no longer fallen
        player_participant.hp_current = 1
        player_participant.is_fallen = False
        player_participant.death_save_successes = 0
        player_participant.death_save_failures = 0
        await db_mutations.update_player_hp(session.player_id, 1)
        sounds.append(SOUND_DEATH_SAVE_CRITICAL)
    elif result.stabilized:
        sounds.append(SOUND_PLAYER_STABILIZED)
    elif result.dead:
        sounds.append(SOUND_PLAYER_DEATH)
    elif result.success:
        sounds.append(SOUND_DEATH_SAVE_SUCCESS)
    else:
        sounds.append(SOUND_DEATH_SAVE_FAIL)

    # Persist
    await db_mutations.save_combat_state(cs.combat_id, cs.to_dict())

    # Publish events
    await publish_game_event(
        session.room,
        E.DICE_ROLL,
        {
            "roll_type": "death_save",
            "roll": result.roll,
            "success": result.success,
            "critical_success": result.critical_success,
            "critical_failure": result.critical_failure,
            "total_successes": result.total_successes,
            "total_failures": result.total_failures,
        },
        event_bus=session.event_bus,
    )
    await _publish_sounds(session, sounds)

    outcome = "stabilized" if result.stabilized else "dead" if result.dead else "continuing"
    if result.critical_success:
        outcome = "revived"
    session.record_event(f"Death save: d{result.roll}, {outcome}")

    response = {
        "roll": result.roll,
        "success": result.success,
        "critical_success": result.critical_success,
        "critical_failure": result.critical_failure,
        "total_successes": result.total_successes,
        "total_failures": result.total_failures,
        "stabilized": result.stabilized,
        "dead": result.dead,
        "revived": result.critical_success,
        "narrative_hint": result.narrative_hint,
    }
    logger.info("request_death_save result: d%d, %s", result.roll, outcome)
    return json.dumps(response)


@function_tool()
@db_tool
async def end_combat(
    context: RunContext[SessionData],
    outcome: str,
) -> str | tuple:
    """End the current combat. Outcome must be 'victory', 'defeat', or 'fled'.
    On victory, calculates XP from defeated enemies (call award_xp separately
    with the returned total). Clears all combat state."""
    logger.info("end_combat called: outcome=%s", outcome)
    session: SessionData = context.userdata

    cs, err = _require_combat(session)
    if err:
        return err

    valid_outcomes = ("victory", "defeat", "fled")
    if outcome.lower() not in valid_outcomes:
        return json.dumps({"error": f"Invalid outcome. Must be one of: {valid_outcomes}"})

    outcome = outcome.lower()

    # Calculate XP from defeated enemies
    xp_total = 0
    defeated_enemies: list[str] = []
    if outcome == "victory":
        enemy_dicts = []
        for p in cs.participants:
            if p.type == "enemy":
                enemy_dicts.append({"xp_value": p.xp_value})
                defeated_enemies.append(p.name)
        xp_total = combat_resolution.calculate_combat_xp(enemy_dicts)

    combat_id = cs.combat_id

    # Clear combat state
    session.combat_state = None

    # Delete from DB
    await db_mutations.delete_combat_state(combat_id)

    # Determine stinger sound
    sound_map = {
        "victory": SOUND_COMBAT_VICTORY,
        "defeat": SOUND_COMBAT_DEFEAT,
        "fled": SOUND_COMBAT_FLED,
    }

    # Publish events
    await publish_game_event(
        session.room,
        E.COMBAT_ENDED,
        {"combat_id": combat_id, "outcome": outcome, "xp_total": xp_total},
        event_bus=session.event_bus,
    )
    await _publish_sounds(session, [sound_map[outcome]])

    session.record_event(f"Combat ended: {outcome}")
    if defeated_enemies:
        loc_name = cs.location_id
        session.record_companion_memory(f"Fought {', '.join(defeated_enemies)} at {loc_name}: {outcome}")

    response = {
        "outcome": outcome,
        "xp_total": xp_total,
        "defeated_enemies": defeated_enemies,
        "note": "Call award_xp with the xp_total to grant experience to the player." if xp_total > 0 else None,
    }
    logger.info("end_combat result: %s, xp=%d", outcome, xp_total)

    # Build gameplay agent with combat summary context for handoff
    from livekit.agents.llm import ChatContext

    from gameplay_agent import create_gameplay_agent

    summary_parts = [f"Combat resolved: {outcome}."]
    if xp_total > 0:
        summary_parts.append(f"XP earned: {xp_total}.")
    if defeated_enemies:
        summary_parts.append(f"Defeated: {', '.join(defeated_enemies)}.")

    summary_ctx = ChatContext()
    summary_ctx.add_message(role="system", content=" ".join(summary_parts))

    agent_type = session.pre_combat_agent_type or REGION_CITY
    session.pre_combat_agent_type = None
    return create_gameplay_agent(
        agent_type, session.location_id, companion=session.companion, chat_ctx=summary_ctx
    ), json.dumps(response)
