"""Apply damage, including zero-HP transitions and their consequences."""

import logging
from functools import partial

import check_resolution_attack
import combat_damage_affinity
import combat_melee_approach
import combat_order_riders
import combat_resolution
import combat_spatial
import concentration_break
import condition_sources
import conditions
import db_mutations
import db_queries
import encounter_facts
import event_types as E
import temp_hp
import wild_shape
from combat_attack_roll import build_attack_dice_roll_payload
from combat_damage_events import record_damage_event
from combat_damage_results import AutomaticDamageResult, SaveDamageResult, attack_fields
from combat_damage_settlement import apply_attack_result as apply_attack_result
from combat_durability import _accrue_durability, _find_equipped
from combat_enemy_active import apply_critical_save, apply_prepared_hit, heal
from combat_events import emit_or_publish
from combat_fate_rolls import packet_save
from combat_fortitude import roll_fortitude
from combat_reaction_defense import halve_psychic
from combat_sound_events import publish_combat_sounds as _publish_sounds
from combat_ui_update import build_combat_ui_update
from combat_zero_hp import _after_hp_change, _handle_hp_zero
from patron_combat_edges import reward_worthy_foe
from patron_zero_hp import trigger_damage_gifts
from session_data import CombatParticipant, SessionData
from tool_support import (
    SOUND_ATTACK_CRITICAL,
    SOUND_ATTACK_HIT,
    SOUND_ATTACK_MISS,
    SOUND_HEARTBEAT,
    SOUND_SAVE_DAMAGE,
)

logger = logging.getLogger("divineruin.tools")


async def _apply_damage(
    session: SessionData,
    attacker,
    action: dict,
    target,
    attack_result: check_resolution_attack.AttackResult | SaveDamageResult | AutomaticDamageResult,
    effective_ac: int,
    *,
    shield_reaction: str | None = None,
    psychic_shield_id: str | None = None,
    rider_target: CombatParticipant | None = None,
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

    rider_target = target if rider_target is None else rider_target
    still_encounter.guard_target(combat_state, target.id)
    attack_result = choir_encounter.guard_damage(combat_state, attacker, target, attack_result)
    psychic_prevented = 0
    if target.id == psychic_shield_id:
        action, attack_result, psychic_prevented = halve_psychic(action, attack_result, target)
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
    if isinstance(attack_result, check_resolution_attack.AttackResult):
        for rider in (attack_result.order_rider, attack_result.sacrifice_rider):
            if rider is not None:
                assert combat_state is not None
                combat_order_riders.consume(combat_state, attacker.id, rider)
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

    # A held roll can outlive the HP and pool it originally saw.
    counted_before = encounter_facts.counted_death(target)
    death_resolved_before = target.hollow_death_resolved
    hp_before, pool_before = target.hp_current, temp_hp.combat_pool(target)
    beast_before = temp_hp.beast_pool(target)
    impact = temp_hp.absorb(
        attack_result.damage,
        hp_before,
        pool_before,
        beast=beast_before,
        hp_floor=conditions.damage_hp_floor(target.conditions),
    )
    if save_damage:
        encounter_facts.record_party_attack(combat_state, attacker, target)
    target.hp_current = impact.hp
    target.temp_hp = impact.temporary
    ended_forms = wild_shape.land_damage(target, impact)
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
    gift, drain_basis = await trigger_damage_gifts(
        session,
        combat_state,
        target,
        hp_before,
        absorbed=impact.absorbed + impact.beast_absorbed,
        queries=queries,
        conn=conn,
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
        self_healed = heal(attacker, drain_basis)

    sounds: list[str] = []
    if save_damage and attack_result.damage > 0:
        sounds.append(SOUND_SAVE_DAMAGE)
    elif not save_damage and attack_result.critical_success:
        sounds.append(SOUND_ATTACK_CRITICAL)
    elif not save_damage and attack_result.hit:
        sounds.append(SOUND_ATTACK_HIT)
    elif not save_damage:
        sounds.append(SOUND_ATTACK_MISS)

    hp_status = combat_resolution.hp_threshold_status(target.hp_current, target.hp_max)
    rose_hollowed = False
    released_from_grapple: list[str] = []
    fortitude_outcome = {}
    if target.hp_current <= 0:
        hp_status, rose_hollowed, released_from_grapple = _handle_hp_zero(
            session,
            combat_state,
            target,
            overkill=impact.overkill,
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

    if isinstance(attack_result, check_resolution_attack.AttackResult) and attack_result.coordinated_rider is not None:
        assert combat_state is not None
        first_hit = None
        if attack_result.hit and not target.is_fallen:
            first_hit = combat_order_riders.FirstHit(
                ally_id=attacker.id,
                target_id=target.id,
                damage_type=attack_result.damage_type,
                magical=bool(action.get("magical")),
                spell_source=action.get("spell_source"),
            )
        combat_order_riders.settle_coordinated(combat_state, attacker.id, attack_result.coordinated_rider, first_hit)

    encounter_facts.record_landing(combat_state, attacker, target, attack_result, hp_before)

    renewals = await _after_hp_change(
        session,
        combat_state,
        target,
        hp_before,
        was_fallen,
        death_resolved_before,
        counted_before,
        queries=queries,
        conn=conn,
    )

    if target.type == "player":
        await mutations.update_player_hp(target.id, target.hp_current, temp_hp=impact.temporary, conn=conn)
    elif rose_hollowed and impact.absorbed:
        await mutations.update_player_temp_hp(target.id, impact.temporary, conn=conn)

    # Combat damage is the canonical concentration-break trigger: a concentrating player who takes
    # damage rolls a CON save (DC scales with the damage); failing it — or being dropped to 0 HP
    # (incapacitated) — ends concentration. The helper no-ops when the player isn't concentrating
    # or the attack dealt no damage; its return (the broken spell id, or None) is narrated below.
    concentration_broken = None
    concentration_receipt: dict = {}
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
            receipt=concentration_receipt,
        )

    if gift_owner and isinstance(attack_result, check_resolution_attack.AttackResult):
        attack_result = combat_damage_affinity.with_landed_damage(
            attack_result,
            attack_result.damage,
            hp_before,
            temporary=pool_before,
            beast=beast_before,
            hp_floor=target.hp_current,
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
    is_hollow = combat_resolution.is_hollow_zone(session.corruption_level)
    armor_inventory = None
    if target.type == "player" and attack_result.damage > 0:
        armor_inventory = await queries.get_player_inventory(target.id, conn=conn)
        if (armor := _find_equipped(armor_inventory, "armor")) is not None:
            durability_results["armor"] = await _accrue_durability(
                session, target.id, armor, 1, is_hollow_zone=is_hollow, conn=conn, sink=sink
            )
    if rider_target.type == "player" and shield_reaction:
        shield_inventory = (
            armor_inventory
            if target is rider_target and armor_inventory is not None
            else await queries.get_player_inventory(rider_target.id, conn=conn)
        )
        if (shield := _find_equipped(shield_inventory, "shield")) is not None:
            durability_results["shield"] = await _accrue_durability(
                session, rider_target.id, shield, 1, is_hollow_zone=is_hollow, conn=conn, sink=sink
            )

    response = {
        **impact.receipt(gift),
        "attacker": attacker.name,
        "action": action.get("name", ""),
        "target": rider_target.name,
        "damage": attack_result.damage,
        "damage_type": attack_result.damage_type,
        "target_hp_status": hp_status,
        "target_fallen": target.is_fallen,
        "narrative_hint": attack_result.narrative_hint,
        "durability": durability_results,
        "concentration_broken": concentration_broken,
        **concentration_receipt,
        "dramatic": attack_result.dramatic,
        "context": attack_result.context,
        "target_rose_hollowed": rose_hollowed,
    }
    if target.id == psychic_shield_id and (psychic_prevented or response["damage"]):
        response["thought_shield_prevented"] = psychic_prevented
    if rider_target is not target:
        response.update(target_id=rider_target.id, damage_target_id=target.id, damage_target=target.name)
    if renewals:
        response["focus_renewals"] = renewals
    if fortitude_outcome:
        response["unholy_fortitude"] = fortitude_outcome
        if fortitude_outcome["success"] and response["context"] == "killing_blow":
            response.update(context="", dramatic=False)
    if "damage_components" in action:
        response["damage_components"] = action["damage_components"]
    if was_fallen:
        response["death_save_failures"] = target.death_save_failures
    log_outcome = record_damage_event(session, attacker, action, target, attack_result)
    if isinstance(attack_result, check_resolution_attack.AttackResult):
        response.update(attack_fields(attack_result, effective_ac, action))
    if action.get("self_heal") == "damage_dealt":
        response["self_healed"] = self_healed
        response["attacker_hp_status"] = combat_resolution.hp_threshold_status(attacker.hp_current, attacker.hp_max)
    if combat_state is not None and not automatic and not defer_concentration:
        apply_prepared_hit(combat_state, attacker, rider_target, action, response)
        apply_critical_save(combat_state, attacker, rider_target, action, response)
    if released_from_grapple:
        response["released_from_grapple"] = released_from_grapple
    if ended_forms:
        response["wild_shape_ended"] = ended_forms
        assert combat_state is not None
        await emit_or_publish(
            sink,
            session.room,
            E.COMBAT_UI_UPDATE,
            build_combat_ui_update(combat_state, wild_shape_ended=ended_forms),
            event_bus=session.event_bus,
        )
    logger.info(
        "resolve_attack_packet result: %s → %s, %s, damage=%d, hp_status=%s",
        attacker.name,
        target.name,
        log_outcome,
        attack_result.damage,
        hp_status,
    )
    return response
