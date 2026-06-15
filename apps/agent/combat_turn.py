"""Combat turn resolution — resolve_enemy_turn and request_death_save tools."""

import json
import logging

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import check_resolution
import combat_phase
import combat_resolution
import concentration_break
import db_mutations
import db_queries
import event_types as E
from combat_support import _accrue_durability, _find_equipped, _publish_sounds, _require_combat
from db_errors import db_tool
from game_events import publish_game_event
from session_data import SessionData
from tool_support import (
    SOUND_ATTACK_CRITICAL,
    SOUND_ATTACK_HIT,
    SOUND_ATTACK_MISS,
    SOUND_DEATH_SAVE_CRITICAL,
    SOUND_DEATH_SAVE_FAIL,
    SOUND_DEATH_SAVE_SUCCESS,
    SOUND_HEARTBEAT,
    SOUND_PLAYER_DEATH,
    SOUND_PLAYER_FALLEN,
    SOUND_PLAYER_STABILIZED,
)

logger = logging.getLogger("divineruin.tools")


@function_tool()
@db_tool
async def declare_phase(
    context: RunContext[SessionData],
    declarations: dict[str, dict],
) -> str:
    """Open a combat phase by recording every combatant's declared action for this
    round, then call resolve_phase to resolve them. Pass a mapping of participant ID
    to that combatant's declaration, e.g.
    {"player_1": {"action": "Longsword", "target_id": "goblin_1"},
     "goblin_1": {"action": "Scimitar", "target_id": "player_1"}}.
    Include the player, every conscious companion, and every enemy that acts this
    phase. Call this once per round at the declaration beat; resolve_phase resolves
    and narrates the whole phase in initiative order."""
    return await _declare_phase_impl(context, declarations)


async def _declare_phase_impl(
    context: RunContext[SessionData],
    declarations: dict[str, dict],
    *,
    mutations=db_mutations,
) -> str:
    logger.info("declare_phase called: %d declarations", len(declarations or {}))
    session: SessionData = context.userdata

    cs = _require_combat(session)
    if cs.beat != combat_phase.PhaseBeat.DECLARATION:
        raise ToolError(f"Not at the declaration beat (current beat: {cs.beat}). Call resolve_phase first.")

    # The pure engine records the declarations and advances DECLARATION -> RESOLUTION.
    # An empty declarations payload is a ValueError from the engine — surface it as a
    # ToolError so the DM re-prompts rather than crashing combat.
    try:
        next_state, _adv = combat_phase.advance_combat_phase(cs, declarations=declarations)
    except ValueError as e:
        raise ToolError(str(e)) from e

    session.combat_state = next_state
    await mutations.save_combat_state(next_state.combat_id, next_state.to_dict())

    response = {
        "beat": next_state.beat,
        "round": next_state.round_number,
        "accepted_actors": list(next_state.pending_declarations.keys()),
    }
    logger.info("declare_phase result: beat=%s, actors=%s", next_state.beat, response["accepted_actors"])
    return json.dumps(response)


@function_tool()
@db_tool
async def resolve_enemy_turn(
    context: RunContext[SessionData],
    enemy_id: str,
    action_name: str,
    target_id: str,
    shield_reaction: str | None = None,
) -> str:
    """Resolve an enemy's attack against a target during combat. Provide the
    enemy's participant ID, which action from their action_pool to use, and
    the target's participant ID. If the player spends a shield reaction (Shield
    Bash, Shield Wall, Intercept) against this attack, pass its name as
    shield_reaction so the shield takes a durability hit. Narrate the result
    dramatically."""
    return await _resolve_enemy_turn_impl(context, enemy_id, action_name, target_id, shield_reaction)


async def _resolve_enemy_turn_impl(
    context: RunContext[SessionData],
    enemy_id: str,
    action_name: str,
    target_id: str,
    shield_reaction: str | None = None,
    *,
    mutations=db_mutations,
    queries=db_queries,
    resolver=check_resolution,
    concentration_break_mod=concentration_break,
) -> str:
    logger.info("resolve_enemy_turn called: enemy=%s, action=%s, target=%s", enemy_id, action_name, target_id)
    session: SessionData = context.userdata

    cs = _require_combat(session)

    enemy = cs.get_participant(enemy_id)
    if enemy is None:
        raise ToolError(f"Enemy '{enemy_id}' not found in combat.")
    if enemy.type not in ("enemy", "companion"):
        raise ToolError(f"'{enemy_id}' is not an enemy or companion.")
    if enemy.is_fallen:
        raise ToolError(f"'{enemy.name}' has fallen and cannot act.")

    # Find action
    action = None
    for a in enemy.action_pool:
        if a.get("name", "").lower() == action_name.lower():
            action = a
            break
    if action is None:
        available = [a.get("name") for a in enemy.action_pool]
        raise ToolError(f"Action '{action_name}' not found. Available: {available}")

    target = cs.get_participant(target_id)
    if target is None:
        raise ToolError(f"Target '{target_id}' not found in combat.")
    if target.is_fallen:
        raise ToolError(f"Target '{target.name}' has already fallen.")

    # Resolve the attack against the target participant, then persist once. The shared
    # packet resolver mutates the target in place and publishes its own HUD events; the
    # phase loop (story-003) reuses it across all packets, persisting once per phase.
    response = await _resolve_attack_packet(
        session,
        enemy,
        action,
        target,
        shield_reaction=shield_reaction,
        mutations=mutations,
        queries=queries,
        resolver=resolver,
        concentration_break_mod=concentration_break_mod,
    )

    await mutations.save_combat_state(cs.combat_id, cs.to_dict())

    return json.dumps(response)


async def _resolve_attack_packet(
    session: SessionData,
    attacker,
    action: dict,
    target,
    *,
    shield_reaction: str | None = None,
    mutations=db_mutations,
    queries=db_queries,
    resolver=check_resolution,
    concentration_break_mod=concentration_break,
) -> dict:
    """Resolve ONE declared attack against CombatParticipant HP.

    Mutates ``target`` in place (hp_current, is_fallen), publishes the attack's
    DICE_ROLL, sounds, and any durability hits in strike order, and returns a
    response dict for the caller (a per-packet narration summary). It does NOT
    persist — the caller owns one ``save_combat_state`` per phase so the multi-packet
    phase loop persists exactly once. ``attacker``/``target`` are CombatParticipants;
    ``action`` is an entry from the attacker's action_pool (weapon-shaped)."""
    attacker_data = {
        "attributes": attacker.attributes,
        "level": attacker.level,
    }

    attack_result = resolver.resolve_attack(
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
            session.record_companion_memory(f"{target.name} was knocked unconscious in combat")
    elif hp_status in ("bloodied", "critical"):
        sounds.append(SOUND_HEARTBEAT)

    # Update DB if target is a player
    if target.type == "player":
        await mutations.update_player_hp(target.id, target.hp_current)

    # Combat damage is the canonical concentration-break trigger: a concentrating player who takes
    # damage rolls a CON save (DC scales with the damage); failing it — or being dropped to 0 HP
    # (incapacitated) — ends concentration. The helper no-ops when the player isn't concentrating
    # or the attack dealt no damage; its return (the broken spell id, or None) is narrated below.
    concentration_broken = None
    if target.type == "player":
        concentration_broken = await concentration_break_mod.break_concentration_on_damage(
            session, attack_result.damage, incapacitated=target.hp_current <= 0
        )

    # Publish events
    await publish_game_event(
        session.room,
        E.DICE_ROLL,
        {
            "roll_type": "attack",
            "attacker": attacker.name,
            "hit": attack_result.hit,
            "roll": attack_result.roll,
            "damage": attack_result.damage,
            "critical": attack_result.critical,
        },
        event_bus=session.event_bus,
    )
    await _publish_sounds(session, sounds)

    # Accrue durability on the player's equipped armor (1 hit per damage taken),
    # and on a shield when the player spends a shield reaction. Hollow zones double.
    # Runs after the attack's DICE_ROLL so ITEM_DURABILITY_HIT follows the strike.
    durability_results: dict = {}
    if target.type == "player" and attack_result.hit:
        inventory = await queries.get_player_inventory(target.id)
        is_hollow = combat_resolution.is_hollow_zone(session.corruption_level)
        armor = _find_equipped(inventory, "armor")
        if armor is not None:
            durability_results["armor"] = await _accrue_durability(
                session, target.id, armor, 1, is_hollow_zone=is_hollow
            )
        if shield_reaction:
            shield = _find_equipped(inventory, "shield")
            if shield is not None:
                durability_results["shield"] = await _accrue_durability(
                    session, target.id, shield, 1, is_hollow_zone=is_hollow
                )

    hit_miss = "hit" if attack_result.hit else "miss"
    session.record_event(f"{attacker.name} attacks {target.name}: {hit_miss}, {attack_result.damage} damage")

    response = {
        "attacker": attacker.name,
        "action": action.get("name", ""),
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
        "durability": durability_results,
        "concentration_broken": concentration_broken,
    }
    logger.info(
        "resolve_attack_packet result: %s → %s, %s, damage=%d, hp_status=%s",
        attacker.name,
        target.name,
        hit_miss,
        attack_result.damage,
        hp_status,
    )
    return response


@function_tool()
@db_tool
async def request_death_save(
    context: RunContext[SessionData],
) -> str:
    """Roll a death saving throw for the fallen player. Call this when the
    player is at 0 HP and it's their turn (or when prompted). Nat 20 restores
    1 HP. Three successes stabilize, three failures mean death."""
    return await _request_death_save_impl(context)


async def _request_death_save_impl(
    context: RunContext[SessionData],
    *,
    mutations=db_mutations,
) -> str:
    logger.info("request_death_save called")
    session: SessionData = context.userdata

    cs = _require_combat(session)

    player_participant = cs.get_participant(session.player_id)
    if player_participant is None:
        raise ToolError("Player not found in combat.")
    if not player_participant.is_fallen:
        raise ToolError("Player has not fallen. Death saves only apply at 0 HP.")

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
        await mutations.update_player_hp(session.player_id, 1)
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
    await mutations.save_combat_state(cs.combat_id, cs.to_dict())

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
