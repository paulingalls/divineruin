"""Apply damage, including zero-HP transitions and their consequences."""

import logging
from functools import partial

import architect_encounter
import check_resolution_attack
import combat_damage_affinity
import combat_grapple
import combat_hollow_death
import combat_melee_approach
import combat_resolution
import combat_spatial
import concentration_break
import condition_sources
import conditions
import db_mutations
import db_queries
import event_types as E
from combat_attack_roll import build_attack_dice_roll_payload
from combat_damage_results import AutomaticDamageResult, SaveDamageResult, attack_fields, freeze_blow, thaw_blow
from combat_durability import _accrue_durability, _find_equipped
from combat_enemy_active import (
    apply_critical_save,
    apply_prepared_hit,
    critical_save_rider,
    heal,
    land_critical_save,
    roll_critical_save,
)
from combat_events import emit_or_publish
from combat_fate_rolls import packet_save
from combat_fortitude import roll_fortitude, try_fortitude
from combat_sound_events import publish_combat_sounds as _publish_sounds
from combat_structures import collapse_wall
from patron_combat_edges import reward_worthy_foe
from patron_zero_hp import lock_lethal_damage_players, trigger_damage_gifts
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


def _handle_hp_zero(
    session: SessionData,
    combat_state: CombatState | None,
    target: CombatParticipant,
    *,
    overkill: int,
    was_fallen: bool,
    hp_status: str,
    sounds: list[str],
    outcome: dict | None = None,
    fortitude_save=None,
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
    if (
        not was_fallen
        and target.unholy_fortitude is not None
        and not target.hollow_death_resolved
        and try_fortitude(target, outcome, fortitude_save)
    ):
        return combat_resolution.hp_threshold_status(target.hp_current, target.hp_max), False, []
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

    if target.is_structure:
        collapse_wall(combat_state, target)
        return hp_status, False, []
    target.is_fallen = True
    combat_hollow_death.mark_destroyed(target)
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


async def apply_attack_result(
    session: SessionData,
    attacker,
    action: dict,
    target,
    attack_result: check_resolution_attack.AttackResult | SaveDamageResult | AutomaticDamageResult | None,
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
    progress=None,
) -> dict:
    if progress is None:
        assert attack_result is not None
        direct = await _apply_damage(
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
        assert direct is not None  # only a fortitude_progress hold pauses
        return direct

    receipt = progress.steps.get("damage_receipt")
    if receipt is not None and "pending" in receipt:
        # A held Unholy Fortitude save paused before HP changed; land the same blow now.
        action, attack_result, effective_ac = thaw_blow(receipt["pending"])
        receipt = None
    if receipt is None:
        assert attack_result is not None
        response = await _apply_damage(
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
            defer_concentration=True,
            fortitude_progress=progress.scope("fortitude"),
        )
        if response is None:
            # Callers treat a present receipt as "already rolled" and resume without re-rolling.
            progress.steps["damage_receipt"] = {"pending": freeze_blow(action, attack_result, effective_ac)}
            return {}
        if "consumed_conditions" in response:
            response["consumed_conditions"] = list(response["consumed_conditions"])
        receipt = {"response": response, "automatic": isinstance(attack_result, AutomaticDamageResult)}
        progress.steps["damage_receipt"] = receipt
    response = receipt["response"]
    if target.type == "player":
        response["concentration_broken"] = await concentration_break_mod.break_concentration_on_damage(
            session,
            response["damage"],
            incapacitated=target.hp_current <= 0,
            damaged_player_id=target.id,
            combat_state=combat_state,
            conn=conn,
            progress=progress.scope("concentration"),
        )
        if progress.paused:
            return {}
    if combat_state is not None and not receipt["automatic"]:
        rider = critical_save_rider(action, response)
        save = None
        if rider is not None:
            # Fate's Thread reaches the target's on-crit save; it resolves before any rider lands.
            save = await packet_save(
                progress.scope("critical_save"),
                session,
                target.id,
                rider["applies_condition"],
                partial(roll_critical_save, attacker, target, rider),
            )
            if save is None:
                return {}
        apply_prepared_hit(combat_state, attacker, target, action, response)
        if save is not None:
            land_critical_save(combat_state, attacker, target, action, response, rider, save)
    del progress.steps["damage_receipt"]
    return response


async def _apply_damage(
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
    defer_concentration: bool = False,
    fortitude_progress=None,
) -> dict | None:
    """Apply already-rolled attack or save damage and its shared combat effects.

    Everything ``roll_attack`` deliberately does not do. Split out for the Beat-3 hold (M29,
    story-016), so the engine can pause on a post-roll, pre-damage reaction window.

    With ``fortitude_progress``, a killing blow's Unholy Fortitude save may be Zhael-held: it is
    rolled before any HP changes, and None is returned while the choice is pending.
    """
    import choir_encounter
    import still_encounter

    still_encounter.guard_target(combat_state, target.id)
    attack_result = choir_encounter.guard_damage(combat_state, attacker, target, attack_result)
    action, attack_result = combat_damage_affinity.apply(target, action, attack_result, state=combat_state)
    from combat_veilrender import mark_radiant

    mark_radiant(target, action, attack_result)
    fortitude_save = None
    if (
        fortitude_progress is not None
        and target.unholy_fortitude is not None
        and not target.is_fallen
        and not target.hollow_death_resolved
        and attack_result.damage >= target.hp_current
    ):
        fortitude_save = await packet_save(
            fortitude_progress, session, target.id, "destruction", partial(roll_fortitude, target)
        )
        if fortitude_save is None:
            return None
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
    still_encounter.record_attack(combat_state, attacker, target, action)

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
    hp_after_damage = max(conditions.damage_hp_floor(target.conditions), hp_before - attack_result.damage)
    target.hp_current = hp_after_damage
    overkill = max(0, attack_result.damage - hp_before) if hp_after_damage == 0 else 0
    if (
        was_fallen
        and attack_result.damage > 0
        and not target.is_dead
        and (target.type == "companion" or target.death_save_failures < 3)
    ):
        failures = 1
        if (
            isinstance(attack_result, check_resolution_attack.AttackResult)
            and attack_result.hit
            and combat_melee_approach.is_melee(action)
        ):
            spatial = combat_spatial.require_spatial(combat_state)
            if combat_spatial.inside(
                combat_spatial.position(spatial, attacker.id), combat_spatial.position(spatial, target.id), 5
            ):
                failures = 2
        target.death_save_failures += failures
        if target.type == "player":
            target.death_save_failures = min(3, target.death_save_failures)
    players = await lock_lethal_damage_players(session, target, hp_before, queries=queries, conn=conn)
    gift = await trigger_damage_gifts(
        session, combat_state, target, hp_before, players=players, queries=queries, conn=conn
    )
    gift_owner = gift.get("gift_owner")
    if gift_owner:
        if sink is None:
            raise ValueError("Automatic patron gifts require a post-commit event sink")
        sink.patron_refreshes[gift_owner["id"]] = (session.room, session.event_bus)

    if not still_encounter.is_owner(combat_state, attacker.id):
        target.conditions = condition_sources.clear_charm_from_damage(
            target.conditions, attacker.id, attack_result.damage
        )

    self_healed = 0
    if action.get("self_heal") == "damage_dealt" and (save_damage or attack_result.hit):
        self_healed = heal(attacker, max(0, hp_before - hp_after_damage))

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
    fortitude_outcome = {}
    if target.hp_current <= 0:
        hp_status, rose_hollowed, released_from_grapple = _handle_hp_zero(
            session,
            combat_state,
            target,
            overkill=overkill,
            was_fallen=was_fallen,
            hp_status=hp_status,
            sounds=sounds,
            outcome=fortitude_outcome,
            fortitude_save=fortitude_save,
        )
        # A foe standing back up on Unholy Fortitude was not defeated, so Worthy Foe waits.
        if hp_before > 0 and target.hp_current <= 0 and combat_state is not None:
            await reward_worthy_foe(combat_state, target, queries=queries, conn=conn)
    elif hp_status in ("bloodied", "critical") and (not save_damage or attack_result.damage > 0):
        sounds.append(SOUND_HEARTBEAT)

    if combat_hollow_death.new_destruction(target, death_resolved_before, was_fallen, hp_before):
        await combat_hollow_death.accrue_death(session, combat_state, target, conn=conn, queries=queries)
        if combat_state is not None and combat_state.choir_encounter is not None:
            choir_encounter.destroyed(combat_state)
        if combat_state is not None and architect_encounter.is_owner(combat_state, target.id):
            architect_encounter.destroyed(combat_state)

    await still_encounter.after_damage(session, combat_state, target, conn=conn, queries=queries, was_fallen=was_fallen)

    # Update DB if target is a player
    if target.type == "player":
        await mutations.update_player_hp(target.id, target.hp_current, conn=conn)

    # Combat damage is the canonical concentration-break trigger: a concentrating player who takes
    # damage rolls a CON save (DC scales with the damage); failing it — or being dropped to 0 HP
    # (incapacitated) — ends concentration. The helper no-ops when the player isn't concentrating
    # or the attack dealt no damage; its return (the broken spell id, or None) is narrated below.
    concentration_broken = None
    if target.type == "player" and not defer_concentration:
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

    if gift_owner and isinstance(attack_result, check_resolution_attack.AttackResult):
        attack_result = combat_damage_affinity.with_landed_damage(
            attack_result, attack_result.damage, hp_before, hp_floor=target.hp_current
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
        **gift,
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
    if fortitude_outcome:
        response["unholy_fortitude"] = fortitude_outcome
        if fortitude_outcome["success"] and response["context"] == "killing_blow":
            response.update(context="", dramatic=False)
    if "damage_components" in action:
        response["damage_components"] = action["damage_components"]
    if was_fallen:
        response["death_save_failures"] = target.death_save_failures
    if isinstance(attack_result, AutomaticDamageResult):
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
        response.update(attack_fields(attack_result, effective_ac))
        log_outcome = hit_miss
    if action.get("self_heal") == "damage_dealt":
        response["self_healed"] = self_healed
        response["attacker_hp_status"] = combat_resolution.hp_threshold_status(attacker.hp_current, attacker.hp_max)
    if combat_state is not None and not automatic and not defer_concentration:
        apply_prepared_hit(combat_state, attacker, target, action, response)
        apply_critical_save(combat_state, attacker, target, action, response)
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
