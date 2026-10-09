"""Shared helpers for combat tool modules."""

import logging
from dataclasses import dataclass, replace

from livekit.agents.llm import ToolError

import check_resolution_attack
import combat_ability
import combat_grapple
import combat_hollow_death
import combat_resolution
import concentration_break
import condition_sources
import conditions
import db_mutations
import db_queries
import event_types as E
import reaction_windows
from combat_action_availability import action_summary
from combat_attack_roll import build_attack_dice_roll_payload, roll_attack
from combat_attack_roll import deserialize_roll as deserialize_roll
from combat_attack_roll import serialize_roll as serialize_roll
from combat_durability import _accrue_durability, _find_equipped
from combat_enemy_active import apply_prepared_hit, heal
from combat_events import emit_or_publish
from combat_sound_events import publish_combat_sounds as _publish_sounds
from condition_restrictions import cannot_act
from kaelen_gift import trigger_iron_resolve
from session_data import CombatParticipant, CombatState, SessionData
from tool_support import (
    SOUND_ATTACK_CRITICAL,
    SOUND_ATTACK_HIT,
    SOUND_ATTACK_MISS,
    SOUND_HEARTBEAT,
    SOUND_HOLLOW_RISE,
    SOUND_PLAYER_FALLEN,
    SOUND_SAVE_DAMAGE,
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
        "cannot_act": list(cannot_act(p.conditions)),
        "prone": conditions.has_condition(p.conditions, "prone"),
        "grappled_by": combat_grapple.grappler_id(p.conditions),
        "creature_id": p.creature_id,
        "catalog_narration": p.catalog_narration,
        "catalog_audio": p.catalog_audio,
        "deferred_effects": p.deferred_effects,
        **action_summary(p),
    }


def _participant_roster(participants: list[CombatParticipant]) -> list[dict]:
    return [_participant_summary(participant) for participant in participants]


def _require_combat(session: SessionData) -> CombatState:
    """Return the combat state, or raise ToolError if not in combat (ADR 0002)."""
    if session.combat_state is None:
        raise ToolError("Not in combat.")
    return session.combat_state


def _handle_hp_zero(
    session: SessionData,
    combat_state: CombatState | None,
    target: CombatParticipant,
    *,
    overkill: int,
    was_fallen: bool,
    hp_status: str,
    sounds: list[str],
) -> tuple[str, bool, list[str]]:
    """Resolve a target dropped to 0 HP — Hollowed rise, instant death, fall, or companion KO.

    The ONE door for every zero-HP transition, whether the damage came from a blow or from the
    caster's own fire; a caller that drives HP to 0 without knocking leaves the flags behind
    (bug 16c5f8a0). The census that keeps it the only door is
    ``tests/combat/test_handle_hp_zero.py::TestTheDoorIsTheOnlyDoor``.

    ``overkill`` is the excess damage past 0. Mutates ``target`` in place
    (``is_fallen``/``is_dead``, or — on a Hollowed rise — ``type``/
    ``hp_current``/``conditions``) and appends the fall/rise sound to ``sounds``. Returns the HP
    status, whether a Hollowed rose, and ids released from this target's grapples."""
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
        return hp_status, True, []

    combat_hollow_death.mark_destroyed(target)
    target.is_fallen = True
    released = combat_grapple.release_from_grappler(combat_state, target.id) if combat_state is not None else []
    # Instant death (M4.4 story-002): overkill (excess damage past 0) >= max HP kills
    # outright — no Fallen grace, no death saves. is_dead is the stronger state; the pure
    # _wrap reads it to end combat without a death-save beat. This is the one site with both
    # overkill + hp_max. Gated on `not was_fallen` so it fires only on the live -> 0
    # transition the spec scopes it to; a hit on an already-downed target is the separate
    # "damage while Fallen" failure mechanic.
    if not was_fallen and overkill >= target.hp_max:
        target.is_dead = True
    sounds.append(SOUND_PLAYER_FALLEN)
    if target.type == "companion" and session.companion and target.id == session.companion.id:
        session.companion.is_conscious = False
        session.record_companion_memory(f"{target.name} was knocked unconscious in combat")
    return hp_status, False, released


async def _resolve_attack_packet(
    session: SessionData,
    attacker,
    action: dict,
    target,
    *,
    target_ac_bonus: int = 0,
    shield_reaction: str | None = None,
    grapple_blocked: bool = False,
    enemies_remaining: int | None = None,
    is_first_attack_of_combat: bool = False,
    mutations=db_mutations,
    queries=db_queries,
    resolver=check_resolution_attack,
    concentration_break_mod=concentration_break,
    combat_state=None,
    conn=None,
    sink=None,
    publish_roll: bool = True,
) -> dict:
    """Resolve ONE declared attack against CombatParticipant HP.

    The composition of ``roll_attack`` and ``apply_attack_result`` — the unpaused path, which
    resolves exactly as it did before the two halves were separable (M29, story-016). Callers
    that must PAUSE between the roll and the damage (the Beat-3 hold) drive the halves directly.

    Mutates ``target`` in place (hp_current, is_fallen), publishes sounds and durability hits,
    and returns a per-packet narration summary. The DICE_ROLL publishes here unless ``publish_roll``
    says a held replay already announced it at the POST_ROLL pause. It does not persist; the
    caller owns the phase save. ``attacker``/``target`` are CombatParticipants and ``action`` is
    weapon-shaped.

    ``shield_reaction`` names the shield-bearing reaction the target spent against THIS blow, and
    is what accrues a durability hit on their shield. Its live producer is the Beat-3 window close
    (combat_reaction_effect.shield_reaction, story-018); ``None`` on every unpaused path."""
    attack_result, effective_ac = roll_attack(
        attacker,
        action,
        target,
        target_ac_bonus=target_ac_bonus,
        enemies_remaining=enemies_remaining,
        is_first_attack_of_combat=is_first_attack_of_combat,
        resolver=resolver,
        combat_state=combat_state,
    )
    summary = await apply_attack_result(
        session,
        attacker,
        action,
        target,
        attack_result,
        effective_ac,
        shield_reaction=shield_reaction,
        mutations=mutations,
        queries=queries,
        concentration_break_mod=concentration_break_mod,
        combat_state=combat_state,
        conn=conn,
        sink=sink,
        publish_roll=publish_roll,
    )
    if (
        attack_result.hit
        and reaction_windows.GRAPPLE_PROPERTY in action.get("properties", [])
        and not grapple_blocked
        and combat_state is not None
        and not target.is_fallen
    ):
        if conditions.has_condition(target.conditions, "grappled"):
            summary["grapple_held"] = True
        elif combat_ability._land_condition_on_one(
            combat_state, target.id, attacker, "grappled", source=attacker.id, packet=summary
        ):
            summary["condition_inflicted"] = "grappled"
        else:
            summary["condition_immune"] = "grappled"
            summary["condition_immunity_source"] = target.condition_immunities["grappled"]
    return summary


@dataclass(frozen=True)
class SaveDamageResult:
    save_type: str
    save_success: bool
    damage: int
    damage_type: str
    narrative_hint: str
    dramatic: bool
    context: str


@dataclass(frozen=True)
class AutomaticDamageResult:
    damage: int
    damage_type: str
    narrative_hint: str = "Automatic damage"
    dramatic: bool = False
    context: str = "turn_start"


async def apply_attack_result(
    session: SessionData,
    attacker,
    action: dict,
    target,
    attack_result: check_resolution_attack.AttackResult | SaveDamageResult | AutomaticDamageResult,
    effective_ac: int,
    *,
    shield_reaction: str | None = None,
    mutations=db_mutations,
    queries=db_queries,
    concentration_break_mod=concentration_break,
    combat_state=None,
    conn=None,
    sink=None,
    publish_roll: bool = True,
) -> dict:
    """Apply already-rolled attack or save damage and its shared combat effects.

    Everything ``roll_attack`` deliberately does not do. Split out for the Beat-3 hold (M29,
    story-016), so the engine can pause on a post-roll, pre-damage reaction window.
    """
    import choir_encounter

    if target.creature_id == "hollow_choir" and combat_state is not None and combat_state.choir_encounter is not None:
        if combat_state.choir_encounter["phase"] != "exposed":
            if attacker.id != target.id:
                raise ValueError("Choir core must be exposed before damage")
            attack_result = replace(attack_result, damage=0)
        bonus = getattr(attack_result, "bonus_damage", 0)
        allowed = choir_encounter.damage(target, attack_result.damage - bonus, attack_result.damage_type)
        allowed += choir_encounter.damage(target, bonus, getattr(attack_result, "bonus_damage_type", None))
        attack_result = replace(attack_result, damage=allowed)
    automatic = isinstance(attack_result, AutomaticDamageResult)
    save_damage = isinstance(attack_result, (SaveDamageResult, AutomaticDamageResult))
    if save_damage and publish_roll:
        raise ValueError("save damage cannot publish an attack roll")

    # Capture pre-hit Fallen state: the instant-death verdict (below) is scoped to the
    # live -> 0 transition (spec game_mechanics_combat.md L350 + on_hp_zero pseudocode L554:
    # "a single source of damage REDUCES HP to 0"). A hit on a target already at 0 is the
    # distinct "damage while Fallen" mechanic (L369: auto death-save failures), not instant
    # death — without this guard overkill = damage - 0 = damage would wrongly flag is_dead.
    was_fallen = target.is_fallen

    # HP is derived from the target's LIVE hp_current and the roll's DAMAGE, never from the roll's
    # absolute ``target_hp_remaining``. On the unpaused path the two are identical by construction
    # — roll_attack was handed this same hp_current a moment earlier. They diverge only when
    # something moved the target's HP between the roll and the damage, which the Beat-3 hold makes
    # reachable: a pause hands the floor back to the DM, and the combat prompt names Inner Fire as
    # one of three things the DM may activate mid-fight (draethar_inner_fire writes this
    # participant's hp_current directly). Writing the stale absolute there HEALS the burn back and
    # hides the fall it caused, so every verdict below reads hp_before instead.
    death_resolved_before = target.hollow_death_resolved
    hp_before = target.hp_current
    overkill = max(0, attack_result.damage - hp_before)
    target.hp_current = max(0, hp_before - attack_result.damage)
    if (
        was_fallen
        and attack_result.damage > 0
        and not target.is_dead
        and (target.type == "companion" or target.death_save_failures < 3)
    ):
        target.death_save_failures += 1
    gift_triggered = trigger_iron_resolve(session, target, hp_before)

    target.conditions = condition_sources.clear_charm_from_damage(target.conditions, attacker.id, attack_result.damage)

    self_healed = 0
    if action.get("self_heal") == "damage_dealt" and (save_damage or attack_result.hit):
        self_healed = heal(attacker, max(0, hp_before - target.hp_current))

    sounds: list[str] = []
    if save_damage and attack_result.damage > 0:
        sounds.append(SOUND_SAVE_DAMAGE)
    elif not save_damage and attack_result.critical_success:
        sounds.append(SOUND_ATTACK_CRITICAL)
    elif not save_damage and attack_result.hit:
        sounds.append(SOUND_ATTACK_HIT)
    elif not save_damage:
        sounds.append(SOUND_ATTACK_MISS)

    # Check HP thresholds
    hp_status = combat_resolution.hp_threshold_status(target.hp_current, target.hp_max)
    rose_hollowed = False
    released_from_grapple: list[str] = []
    if target.hp_current <= 0:
        hp_status, rose_hollowed, released_from_grapple = _handle_hp_zero(
            session,
            combat_state,
            target,
            overkill=overkill,
            was_fallen=was_fallen,
            hp_status=hp_status,
            sounds=sounds,
        )
    elif hp_status in ("bloodied", "critical") and (not save_damage or attack_result.damage > 0):
        sounds.append(SOUND_HEARTBEAT)

    if combat_hollow_death.new_destruction(target, death_resolved_before, was_fallen, hp_before):
        await combat_hollow_death.accrue_death(session, combat_state, target, conn=conn, queries=queries)
        if combat_state is not None and combat_state.choir_encounter is not None:
            choir_encounter.destroyed(combat_state)

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
    if publish_roll:
        await emit_or_publish(
            sink,
            session.room,
            E.DICE_ROLL,
            build_attack_dice_roll_payload(attacker, attack_result),
            event_bus=session.event_bus,
        )
    await _publish_sounds(session, sounds, sink=sink)

    # Armor wears per damage TAKEN, a shield per reaction SPENT (spec game_mechanics_crafting.md
    # L536-537): two rules, which disagree on a 0-damage blow — hence the nested gates. Hollow
    # zones double. Runs after the resolution's DICE_ROLL so ITEM_DURABILITY_HIT follows the damage.
    durability_results: dict = {}
    if target.type == "player" and (attack_result.damage > 0 or shield_reaction):
        inventory = await queries.get_player_inventory(target.id, conn=conn)
        is_hollow = combat_resolution.is_hollow_zone(session.corruption_level)
        if attack_result.damage > 0:
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

    response = {
        "attacker": attacker.name,
        "action": action.get("name", ""),
        "target": target.name,
        "damage": attack_result.damage,
        "damage_type": attack_result.damage_type,
        "target_hp_status": hp_status,
        "target_fallen": target.is_fallen,
        "narrative_hint": attack_result.narrative_hint,
        "durability": durability_results,
        "concentration_broken": concentration_broken,
        "dramatic": attack_result.dramatic,
        "context": attack_result.context,
        "target_rose_hollowed": rose_hollowed,
    }
    if gift_triggered:
        response["gift_triggered"] = gift_triggered
    if automatic:
        log_outcome = "automatic damage"
        session.record_event(
            f"{attacker.name} uses {action.get('name', '')} on {target.name}: {attack_result.damage} automatic damage"
        )
    elif isinstance(attack_result, SaveDamageResult):
        save_outcome = "succeeded" if attack_result.save_success else "failed"
        session.record_event(
            f"{attacker.name} uses {action.get('name', '')} on {target.name}: "
            f"{attack_result.save_type} save {save_outcome}, {attack_result.damage} damage"
        )
        log_outcome = f"{attack_result.save_type} save {save_outcome}"
    else:
        hit_miss = "hit" if attack_result.hit else "miss"
        session.record_event(f"{attacker.name} attacks {target.name}: {hit_miss}, {attack_result.damage} damage")
        response.update(
            hit=attack_result.hit,
            roll=attack_result.roll,
            attack_total=attack_result.attack_total,
            target_ac=effective_ac,
            critical=attack_result.critical_success,
            bonus_damage=attack_result.bonus_damage,
            bonus_damage_type=attack_result.bonus_damage_type,
            consumed_conditions=attack_result.consumed_conditions,
        )
        log_outcome = hit_miss
    if action.get("self_heal") == "damage_dealt":
        response["self_healed"] = self_healed
        response["attacker_hp_status"] = combat_resolution.hp_threshold_status(attacker.hp_current, attacker.hp_max)
    if combat_state is not None and not automatic:
        apply_prepared_hit(combat_state, attacker, target, action, response)
    if released_from_grapple:
        response["released_from_grapple"] = released_from_grapple
    logger.info(
        "resolve_attack_packet result: %s → %s, %s, damage=%d, hp_status=%s",
        attacker.name,
        target.name,
        log_outcome,
        attack_result.damage,
        hp_status,
    )
    return response
