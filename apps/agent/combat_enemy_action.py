"""Enemy actions that combine attacks, damage saves, and conditions."""

from dataclasses import replace
from functools import partial
from typing import TYPE_CHECKING

import architect_entomb
import check_resolution_save
import combat_damage_affinity
import combat_wrongdoing
import concentration_break
import conditions
import encounter_facts
import event_types as E
from combat_ability import _attach_riders
from combat_condition_target import _resolve_condition_target
from combat_damage import apply_attack_result
from combat_damage_results import SaveDamageResult
from combat_down import damage_target_unavailable, has_damage
from combat_enemy_active import already_hollowed
from combat_enemy_conditions import land_outcome
from combat_events import emit_or_publish
from combat_fate_rolls import packet_save, saved_throw, store_throw
from combat_legendary_resistance import finalize_save, override_fields
from combat_support import _resolve_attack_packet
from dice import roll as dice_roll
from session_data import CombatParticipant, SessionData

if TYPE_CHECKING:
    from declarations import Declaration


def is_save_damage_action(action: dict) -> bool:
    return action.get("resolution") == "save" or action.get("half_on_success") is True


def is_combined_attack_action(action: dict) -> bool:
    return (
        (action.get("resolution") == "hit_then_save" or bool(action.get("applies_condition")))
        and has_damage(action)
        and not is_save_damage_action(action)
    )


def _save_fields(result, roller_id: str) -> dict:
    return {
        **override_fields(result),
        **encounter_facts.rally_receipt(roller_id, result.rally_sources),
        "save_type": result.save_type,
        "save_roll": result.roll,
        "save_total": result.total,
        "save_dc": result.dc,
        "save_success": result.success,
    }


def failed_conditions(target: CombatParticipant, action: dict) -> tuple[str, ...]:
    if "resolution" in action:
        conditions = [rider["applies_condition"] for rider in action["conditions_on_failure"]]
    else:
        condition = action.get("applies_condition")
        conditions = [condition] if condition is not None else []
    return tuple(condition for condition in conditions if not already_hollowed(target, condition))


async def _resolve_enemy_condition_packet(
    session: SessionData,
    attacker: CombatParticipant,
    decl: "Declaration",
    action: dict,
    *,
    state,
    conn,
    save_resolver=check_resolution_save,
    concentration_break_mod=concentration_break,
    reaction_save_advantage: bool = False,
    progress=None,
) -> dict:
    cond_type = action.get("applies_condition", action["name"])
    target, waste = _resolve_condition_target(state, attacker, decl, allow_self=action.get("resolution") == "save")
    if waste is not None:
        return waste
    assert target is not None
    entomb = architect_entomb.matches(attacker, action)
    result = await packet_save(
        progress,
        session,
        target.id,
        cond_type,
        partial(
            save_resolver.roll_participant_save,
            target,
            action["save"],
            action["dc"],
            cond_type,
            dc_mod=attacker.dc_mod,
            bonus_dice_eligible=False,
            advantage=reaction_save_advantage,
            combat_state=state,
        ),
        state=state,
    )
    if result is None:
        return {}
    encounter_facts.record_party_attack(state, attacker, target)
    result = finalize_save(state, target, result, failed_conditions=failed_conditions(target, action))
    summary = {
        "actor_id": attacker.id,
        "resolved": True,
        "declaration_type": str(decl.type),
        "action": decl.action,
        "target": target.name,
        **_save_fields(result, target.id),
    }
    if reaction_save_advantage and result.advantage_applied:
        summary["save_advantage"] = True
    if (item_save_source := target.save_advantages.get(result.save_type)) and result.advantage_applied:
        summary["save_advantage_source"] = item_save_source
    if entomb:
        architect_entomb.land(state, attacker, target, summary)
        return summary
    await land_outcome(
        session,
        attacker,
        target,
        decl,
        action,
        result,
        summary,
        state=state,
        conn=conn,
        concentration_break_mod=concentration_break_mod,
        duration=action.get("duration"),
    )
    return summary


async def resolve_combined_attack_action(
    session: SessionData,
    attacker: CombatParticipant,
    target: CombatParticipant,
    decl: "Declaration",
    action: dict,
    *,
    state,
    conn,
    mutations,
    queries,
    resolver,
    concentration_break_mod,
    sink,
    target_ac_bonus: int,
    shield_reaction: str | None,
    enemies_remaining: int,
    is_first_attack_of_combat: bool,
    reaction_save_advantage: bool,
    publish_roll: bool,
    progress=None,
) -> dict:
    steps = progress.steps if progress is not None else {}
    summary = steps.get("attack")
    if summary is None:
        summary = await _resolve_attack_packet(
            session,
            attacker,
            action,
            target,
            target_ac_bonus=target_ac_bonus,
            shield_reaction=shield_reaction,
            enemies_remaining=enemies_remaining,
            is_first_attack_of_combat=is_first_attack_of_combat,
            mutations=mutations,
            queries=queries,
            resolver=resolver,
            concentration_break_mod=concentration_break_mod,
            combat_state=state,
            conn=conn,
            sink=sink,
            publish_roll=publish_roll,
            progress=progress,
        )
        if progress is not None and progress.paused:
            return {}
        steps["attack"] = summary
    if summary["hit"] and not target.is_fallen:
        condition = await _resolve_enemy_condition_packet(
            session,
            attacker,
            decl,
            action,
            state=state,
            conn=conn,
            concentration_break_mod=concentration_break_mod,
            reaction_save_advantage=reaction_save_advantage,
            progress=progress,
        )
        if progress is not None and progress.paused:
            return {}
        summary.update({key: value for key, value in condition.items() if key not in {"resolved", "reason"}})
        # A bare `reason` means "this packet did nothing" everywhere else in the resolver, so the
        # condition half's own waste rides a namespaced key: the damage landed, and the DM must not
        # read the condition's refusal as the whole blow's.
        if (condition_reason := condition.get("reason")) is not None:
            summary["condition_reason"] = condition_reason
    return summary


async def resolve_save_damage_action(
    session: SessionData,
    attacker: CombatParticipant,
    decl: "Declaration",
    action: dict,
    *,
    state,
    conn,
    mutations,
    queries,
    concentration_break_mod,
    sink,
    reaction_save_advantage: bool,
    progress=None,
) -> dict:
    target, waste = _resolve_condition_target(
        state, attacker, decl, allow_self=action.get("resolution") == "save", damage=True
    )
    if waste is not None:
        return waste
    assert target is not None
    cond_type = action.get("applies_condition")
    steps = progress.steps if progress is not None else {}
    selected_save = steps.get("selected_save")
    if selected_save is not None:
        result = saved_throw(selected_save)
        damage_result = None
    else:
        result = await packet_save(
            progress,
            session,
            target.id,
            cond_type or action["name"],
            partial(
                check_resolution_save.roll_participant_save,
                target,
                action["save"],
                action["dc"],
                cond_type or action["name"],
                dc_mod=attacker.dc_mod,
                bonus_dice_eligible=False,
                advantage=reaction_save_advantage,
                combat_state=state,
            ),
            state=state,
        )
        if result is None:
            return {}
        combat_wrongdoing.record_attack(state, attacker, target)
        # The encounter-role overlay scales this the way it scales a weapon hit (check_resolution_attack
        # multiplies the final total by damage_mult): a Boss's wave must burn like a Boss. dc_mod already
        # rides the save above, so dropping the multiplier here would role-scale half the action.
        rolled_damage = max(0, int(dice_roll(action["damage"]).total * attacker.damage_mult))
        damage_result = SaveDamageResult(
            save_type=result.save_type,
            save_success=result.success,
            damage=rolled_damage,
            damage_type=action.get("damage_type", "none"),
            narrative_hint=result.narrative_hint,
            dramatic=result.dramatic,
            context=result.context,
        )
        if not result.success:
            _, adjusted = combat_damage_affinity.apply(target, action, damage_result, state=state)
            result = finalize_save(
                state,
                target,
                result,
                failed_conditions=failed_conditions(target, action),
                failed_damage=adjusted.damage,
            )
        if result.success:
            damage_result = replace(
                damage_result,
                save_success=True,
                damage=0 if action.get("save_success_damage") == "none" else rolled_damage // 2,
                narrative_hint=result.narrative_hint,
            )
        # Announced here because the shared applicator refuses to publish an attack roll for save damage.
        await emit_or_publish(
            sink,
            session.room,
            E.DICE_ROLL,
            {
                **override_fields(result),
                **encounter_facts.rally_receipt(target.id, result.rally_sources),
                "roll_type": "saving_throw",
                "save_type": result.save_type,
                "roll": result.roll,
                "total": result.total,
                "success": result.success,
                "dramatic": result.dramatic,
                "context": result.context,
                "damage": damage_result.damage,
            },
            event_bus=session.event_bus,
        )
    summary = await apply_attack_result(
        session,
        attacker,
        action,
        target,
        damage_result,
        result.dc,
        mutations=mutations,
        queries=queries,
        concentration_break_mod=concentration_break_mod,
        combat_state=state,
        conn=conn,
        sink=sink,
        publish_roll=False,
        progress=progress,
    )
    if progress is not None and progress.paused:
        steps["selected_save"] = store_throw(result)
        return {}
    summary.update(_save_fields(result, target.id))
    summary["half_on_success"] = action.get("save_success_damage", "half") == "half"
    summary["damage_halved"] = result.success and summary["half_on_success"]
    if reaction_save_advantage and result.advantage_applied:
        summary["save_advantage"] = True
    if (item_save_source := target.save_advantages.get(result.save_type)) and result.advantage_applied:
        summary["save_advantage_source"] = item_save_source
    if (cond_type is not None or "resolution" in action) and not target.is_fallen:
        await land_outcome(
            session,
            attacker,
            target,
            decl,
            action,
            result,
            summary,
            state=state,
            conn=conn,
            concentration_break_mod=concentration_break_mod,
            duration=action.get("duration"),
        )
    summary["actor_id"] = attacker.id
    summary["resolved"] = True
    summary["declaration_type"] = str(decl.type)
    return summary


async def resolve_enemy_strike(
    session,
    attacker,
    decl,
    action,
    *,
    state,
    packet,
    conn,
    mutations,
    queries,
    resolver,
    concentration_break_mod,
    sink,
    reaction_ac_bonus,
    shield_reaction,
    reaction_save_advantage,
    publish_roll,
    progress=None,
):
    if not attacker.is_ally and action is not None and is_save_damage_action(action):
        return await resolve_save_damage_action(
            session,
            attacker,
            decl,
            action,
            state=state,
            conn=conn,
            mutations=mutations,
            queries=queries,
            concentration_break_mod=concentration_break_mod,
            sink=sink,
            reaction_save_advantage=reaction_save_advantage,
            progress=progress,
        )

    if not attacker.is_ally and action is not None and is_combined_attack_action(action):
        target = state.get_participant(decl.target_id) if decl.target_id else None
        if target is None:
            return {"actor_id": packet.actor_id, "resolved": False, "reason": f"target '{decl.target_id}' not found"}
        if damage_target_unavailable(target):
            return {"actor_id": packet.actor_id, "resolved": False, "reason": f"{target.name} already fell"}
        summary = await resolve_combined_attack_action(
            session,
            attacker,
            target,
            decl,
            action,
            state=state,
            conn=conn,
            mutations=mutations,
            queries=queries,
            resolver=resolver,
            concentration_break_mod=concentration_break_mod,
            sink=sink,
            target_ac_bonus=state.ac_modifiers.get(target.id, 0) + reaction_ac_bonus,
            shield_reaction=shield_reaction,
            enemies_remaining=sum(1 for p in state.participants if p.type == "enemy" and not p.is_fallen),
            is_first_attack_of_combat=not state.first_attack_resolved,
            reaction_save_advantage=reaction_save_advantage,
            progress=progress,
            publish_roll=publish_roll,
        )
        if progress is not None and progress.paused:
            return {}
        if summary.get("consumed_conditions"):
            attacker.conditions = conditions.remove_conditions(attacker.conditions, summary["consumed_conditions"])
        state.first_attack_resolved = True
        summary["actor_id"] = packet.actor_id
        summary["resolved"] = True
        return _attach_riders(summary, attacker, decl)

    if not attacker.is_ally and action is not None and action.get("applies_condition"):
        return await _resolve_enemy_condition_packet(
            session,
            attacker,
            decl,
            action,
            state=state,
            conn=conn,
            concentration_break_mod=concentration_break_mod,
            reaction_save_advantage=reaction_save_advantage,
            progress=progress,
        )

    return None
