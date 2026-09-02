"""Shared helpers for combat tool modules."""

import logging
from dataclasses import replace

from livekit.agents.llm import ToolError

import check_resolution_attack
import combat_resolution
import concentration_break
import conditions
import db_mutations
import db_queries
import event_types as E
from combat_durability import _accrue_durability, _find_equipped
from combat_events import EventSink, emit_or_publish
from dramatic import DramaticContext, evaluate_dramatic_context
from session_data import CombatParticipant, CombatState, SessionData
from tool_support import (
    SOUND_ATTACK_CRITICAL,
    SOUND_ATTACK_HIT,
    SOUND_ATTACK_MISS,
    SOUND_HEARTBEAT,
    SOUND_HOLLOW_RISE,
    SOUND_PLAYER_FALLEN,
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


def _require_combat(session: SessionData) -> CombatState:
    """Return the combat state, or raise ToolError if not in combat (ADR 0002)."""
    if session.combat_state is None:
        raise ToolError("Not in combat.")
    return session.combat_state


async def _publish_sounds(session: SessionData, sounds: list[str], *, sink: EventSink | None = None) -> None:
    """Publish multiple sound events. When ``sink`` is active the events buffer until the phase
    transaction commits (rollback-safe); otherwise they publish immediately."""
    for sound in sounds:
        await emit_or_publish(
            sink,
            session.room,
            E.PLAY_SOUND,
            {"sound_name": sound},
            event_bus=session.event_bus,
        )


def _handle_hp_zero(
    session: SessionData,
    target: CombatParticipant,
    attack_result,
    *,
    was_fallen: bool,
    hp_status: str,
    sounds: list[str],
) -> tuple[str, bool]:
    """Resolve a target dropped to 0 HP — Hollowed rise, instant death, fall, or companion KO.

    Called from ``_resolve_attack_packet`` only when ``target.hp_current <= 0``. Mutates
    ``target`` in place (``is_fallen``/``is_dead``, or — on a Hollowed rise — ``type``/
    ``hp_current``/``conditions``) and appends the fall/rise sound to ``sounds``. Returns
    ``(hp_status, rose_hollowed)``: ``hp_status`` is recomputed only when a Hollowed rise restores
    HP (otherwise the caller's pre-computed value passes through unchanged); ``rose_hollowed`` tells
    the DM to narrate the corpse rising instead of the target falling."""
    if not was_fallen and target.type == "player" and conditions.hollowed_stage(target.conditions) >= 2:
        # Temporary Hollowed rise (M4.4 story-008): a Stage-2+ Hollowed player at 0 HP does NOT
        # fall — their corpse rises as a hostile Temporary Hollowed combatant (HP=50% of max,
        # hits add 1d6 necrotic, immune to Charmed/Frightened/Poisoned) that blocks combat-end
        # until destroyed (combat_phase._wrap). Transform in place: flipping `type` makes the
        # engine's player-defeat gate go dormant (no player participant) and the echo block
        # victory, AND it deliberately suppresses the player-HP write + concentration-break +
        # armor-durability accrual below — the echo's HP is the monster's, not the player's.
        # The persisted Hollowed condition is left intact; trigger_character_death reads it at
        # the echo's destruction to mark hollow_killed and clear it.
        target.type = "temporary_hollowed"
        target.hp_current = max(1, target.hp_max // 2)
        target.conditions = conditions.apply_condition(target.conditions, "temporary_hollowed")
        hp_status = combat_resolution.hp_threshold_status(target.hp_current, target.hp_max)
        sounds.append(SOUND_HOLLOW_RISE)
        return hp_status, True

    target.is_fallen = True
    # Instant death (M4.4 story-002): overkill (excess damage past 0) >= max HP kills
    # outright — no Fallen grace, no death saves. is_dead is the stronger state; the pure
    # _wrap reads it to end combat without a death-save beat. This is the one site with both
    # attack_result + hp_max. Gated on `not was_fallen` so it fires only on the live -> 0
    # transition the spec scopes it to; a hit on an already-downed target is the separate
    # "damage while Fallen" failure mechanic.
    if not was_fallen and attack_result.overkill >= target.hp_max:
        target.is_dead = True
    sounds.append(SOUND_PLAYER_FALLEN)
    # Handle companion KO
    if target.type == "companion" and session.companion and target.id == session.companion.id:
        session.companion.is_conscious = False
        session.record_companion_memory(f"{target.name} was knocked unconscious in combat")
    return hp_status, False


async def _resolve_attack_packet(
    session: SessionData,
    attacker,
    action: dict,
    target,
    *,
    target_ac_bonus: int = 0,
    shield_reaction: str | None = None,
    enemies_remaining: int | None = None,
    is_first_attack_of_combat: bool = False,
    mutations=db_mutations,
    queries=db_queries,
    resolver=check_resolution_attack,
    concentration_break_mod=concentration_break,
    combat_state=None,
    conn=None,
    sink=None,
) -> dict:
    """Resolve ONE declared attack against CombatParticipant HP.

    Mutates ``target`` in place (hp_current, is_fallen), publishes the attack's
    DICE_ROLL, sounds, and any durability hits in strike order, and returns a
    response dict for the caller (a per-packet narration summary). It does NOT
    persist — the caller owns one ``save_combat_state`` per phase so the multi-packet
    phase loop persists exactly once. ``attacker``/``target`` are CombatParticipants;
    ``action`` is an entry from the attacker's action_pool (weapon-shaped).

    ``shield_reaction`` remains unwired because player reactions resolve through
    ``activate`` and ``validate_reaction_activation``, outside the attack packet. It is therefore
    ``None`` on the live path; direct durability tests exercise the accrual seam."""
    attacker_data = {
        "attributes": attacker.attributes,
        "level": attacker.level,
        # Attacker's active conditions (M4.3): resolve_attack folds Exhausted into the roll,
        # Prone/Blinded into disadvantage, and Enraged into +2 damage.
        "conditions": attacker.conditions,
    }

    # ``target_ac_bonus`` is the target's phase-scoped AC modifier (Defend's +2, M4.2);
    # the live caller passes state.ac_modifiers[target.id]. Defaults to 0 for direct callers.
    # The target's condition AC modifier (M4.3, e.g. Enraged -2 AC) makes them easier to hit.
    target_condition_ac = conditions.get_condition_effects(target.conditions).ac_modifier
    effective_ac = target.ac + target_ac_bonus + target_condition_ac
    attack_result = resolver.resolve_attack(
        attacker_data,
        action,
        effective_ac,
        target.hp_current,
        # Encounter-role overlay (M4.7, story-001): a role-derived attacker carries a flat to-hit
        # bonus and a damage multiplier (Elite/Boss boost, Minion soften). Players carry identity
        # defaults, so the player attack path is unchanged.
        attack_mod=attacker.attack_mod,
        damage_mult=attacker.damage_mult,
    )

    # Dramatic-dice (M4.5, story-004): the resolver's intrinsic verdict (nat-20/nat-1/
    # killing-blow) is the floor. If it didn't fire, PROMOTE on the encounter-context
    # signals only the caller can see — the last enemy standing, or the opening strike.
    # The caller supplies these (combat_packet._resolve_one_packet counts non-fallen
    # enemies + tracks first attack); never downgrade an already-dramatic intrinsic verdict.
    if not attack_result.dramatic:
        verdict = evaluate_dramatic_context(
            DramaticContext(
                roll_type="attack",
                enemies_remaining=enemies_remaining,
                is_first_attack_of_combat=is_first_attack_of_combat,
            )
        )
        if verdict.dramatic:
            attack_result = replace(attack_result, dramatic=True, context=verdict.context)

    # Capture pre-hit Fallen state: the instant-death verdict (below) is scoped to the
    # live -> 0 transition (spec game_mechanics_combat.md L350 + on_hp_zero pseudocode L554:
    # "a single source of damage REDUCES HP to 0"). A hit on a target already at 0 is the
    # distinct "damage while Fallen" mechanic (L369: auto death-save failures), not instant
    # death — without this guard overkill = damage - 0 = damage would wrongly flag is_dead.
    was_fallen = target.is_fallen

    # Update target HP
    target.hp_current = attack_result.target_hp_remaining

    # Determine sounds
    sounds: list[str] = []
    if attack_result.critical_success:
        sounds.append(SOUND_ATTACK_CRITICAL)
    elif attack_result.hit:
        sounds.append(SOUND_ATTACK_HIT)
    else:
        sounds.append(SOUND_ATTACK_MISS)

    # Check HP thresholds
    hp_status = combat_resolution.hp_threshold_status(target.hp_current, target.hp_max)
    rose_hollowed = False
    if target.hp_current <= 0:
        hp_status, rose_hollowed = _handle_hp_zero(
            session, target, attack_result, was_fallen=was_fallen, hp_status=hp_status, sounds=sounds
        )
    elif hp_status in ("bloodied", "critical"):
        sounds.append(SOUND_HEARTBEAT)

    # Update DB if target is a player
    if target.type == "player":
        await mutations.update_player_hp(target.id, target.hp_current, conn=conn)

    # Combat damage is the canonical concentration-break trigger: a concentrating player who takes
    # damage rolls a CON save (DC scales with the damage); failing it — or being dropped to 0 HP
    # (incapacitated) — ends concentration. The helper no-ops when the player isn't concentrating
    # or the attack dealt no damage; its return (the broken spell id, or None) is narrated below.
    concentration_broken = None
    if target.type == "player":
        # Thread the phase loop's WORKING combat state so the concentration break strips the linked
        # condition (Bless → blessed) from the state that actually gets persisted — during resolution
        # session.combat_state is still the pristine pre-phase copy (combat_turn adopts the working
        # state only post-commit). Direct/OOC callers pass None and fall back to session.combat_state.
        concentration_broken = await concentration_break_mod.break_concentration_on_damage(
            session,
            attack_result.damage,
            incapacitated=target.hp_current <= 0,
            damaged_player_id=target.id,
            combat_state=combat_state,
            conn=conn,
        )

    # Publish events (buffered into ``sink`` during the phase tx; released post-commit)
    await emit_or_publish(
        sink,
        session.room,
        E.DICE_ROLL,
        {
            "roll_type": "attack",
            "attacker": attacker.name,
            "hit": attack_result.hit,
            "roll": attack_result.roll,
            "damage": attack_result.damage,
            "critical": attack_result.critical_success,
            "dramatic": attack_result.dramatic,
            "context": attack_result.context,
        },
        event_bus=session.event_bus,
    )
    await _publish_sounds(session, sounds, sink=sink)

    # Accrue durability on the player's equipped armor (1 hit per damage taken),
    # and on a shield when the player spends a shield reaction. Hollow zones double.
    # Runs after the attack's DICE_ROLL so ITEM_DURABILITY_HIT follows the strike.
    durability_results: dict = {}
    if target.type == "player" and attack_result.hit:
        inventory = await queries.get_player_inventory(target.id, conn=conn)
        is_hollow = combat_resolution.is_hollow_zone(session.corruption_level)
        armor = _find_equipped(inventory, "armor")
        if armor is not None:
            durability_results["armor"] = await _accrue_durability(
                session, target.id, armor, 1, is_hollow_zone=is_hollow, conn=conn, sink=sink
            )
        if shield_reaction:
            shield = _find_equipped(inventory, "shield")
            if shield is not None:
                durability_results["shield"] = await _accrue_durability(
                    session, target.id, shield, 1, is_hollow_zone=is_hollow, conn=conn, sink=sink
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
        "target_ac": effective_ac,
        "damage": attack_result.damage,
        "damage_type": attack_result.damage_type,
        "critical": attack_result.critical_success,
        "target_hp_status": hp_status,
        "target_fallen": target.is_fallen,
        "narrative_hint": attack_result.narrative_hint,
        "durability": durability_results,
        "concentration_broken": concentration_broken,
        "dramatic": attack_result.dramatic,
        "context": attack_result.context,
        # Bonus-damage rider (M4.4 story-008): the necrotic bite a Temporary Hollowed attacker
        # adds, for the DM to voice. 0/None on a normal hit.
        "bonus_damage": attack_result.bonus_damage,
        "bonus_damage_type": attack_result.bonus_damage_type,
        # Beneficial conditions whose +1d4 this swing rolled into the to-hit (M4.8 story-003). The
        # caller (_resolve_one_packet) removes these from the attacker so a multi-swing sequence
        # consumes the single-use die exactly once.
        "consumed_conditions": attack_result.consumed_conditions,
        # Set when this hit raised a Stage-2+ Hollowed target as a Temporary Hollowed echo
        # instead of felling them — the DM narrates the corpse rising.
        "target_rose_hollowed": rose_hollowed,
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
