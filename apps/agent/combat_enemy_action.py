"""Enemy actions that combine attacks, damage saves, and conditions."""

from typing import TYPE_CHECKING

import check_resolution_save
import concentration_break
import event_types as E
from combat_ability import _resolve_condition_target, land_condition_on_participant
from combat_events import emit_or_publish
from combat_support import SaveDamageResult, _resolve_attack_packet, apply_attack_result
from condition_restrictions import cannot_act
from dice import roll as dice_roll
from session_data import CombatParticipant, SessionData

if TYPE_CHECKING:
    from declarations import Declaration


def has_damage(action: dict) -> bool:
    return action.get("damage") not in (None, "", "0", 0)


def is_save_damage_action(action: dict) -> bool:
    return action.get("half_on_success") is True


def is_combined_attack_action(action: dict) -> bool:
    return bool(action.get("applies_condition")) and has_damage(action) and not is_save_damage_action(action)


def _save_fields(result) -> dict:
    return {
        "save_type": result.save_type,
        "save_roll": result.roll,
        "save_total": result.total,
        "save_dc": result.dc,
        "save_success": result.success,
    }


async def _apply_condition_result(
    session: SessionData,
    attacker: CombatParticipant,
    target: CombatParticipant,
    decl: "Declaration",
    cond_type: str,
    result,
    summary: dict,
    *,
    state,
    conn,
    concentration_break_mod,
) -> None:
    if result.success:
        summary["condition_resisted"] = cond_type
        return
    if land_condition_on_participant(
        state,
        attacker,
        decl,
        cond_type,
        source=decl.action or "",
        packet=summary,
    ):
        summary["condition_inflicted"] = cond_type
        if target.type == "player" and cannot_act(({"type": cond_type},)):
            broken = await concentration_break_mod.break_concentration_on_incapacitation(
                session, target.id, combat_state=state, conn=conn
            )
            if broken is not None:
                summary["concentration_broken"] = broken
        return
    summary["condition_immune"] = cond_type
    if item_immunity := target.condition_immunities.get(cond_type):
        summary["condition_immunity_source"] = item_immunity
    if cond_type == "prone" and target.prone_immunity:
        summary["prone_immunity"] = target.prone_immunity


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
) -> dict:
    cond_type = action["applies_condition"]
    target, waste = _resolve_condition_target(state, attacker, decl, allow_self=False)
    if waste is not None:
        return waste
    assert target is not None
    result = save_resolver.roll_participant_save(
        target,
        action["save"],
        action["dc"],
        cond_type,
        dc_mod=attacker.dc_mod,
        bonus_dice_eligible=False,
        advantage=reaction_save_advantage,
    )
    summary = {
        "actor_id": attacker.id,
        "resolved": True,
        "declaration_type": str(decl.type),
        "action": decl.action,
        "target": target.name,
        **_save_fields(result),
    }
    if reaction_save_advantage and result.advantage_applied:
        summary["save_advantage"] = True
    if (item_save_source := target.save_advantages.get(result.save_type)) and result.advantage_applied:
        summary["save_advantage_source"] = item_save_source
    await _apply_condition_result(
        session,
        attacker,
        target,
        decl,
        cond_type,
        result,
        summary,
        state=state,
        conn=conn,
        concentration_break_mod=concentration_break_mod,
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
) -> dict:
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
    )
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
        )
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
) -> dict:
    target, waste = _resolve_condition_target(state, attacker, decl, allow_self=False)
    if waste is not None:
        return waste
    assert target is not None
    cond_type = action.get("applies_condition")
    result = check_resolution_save.roll_participant_save(
        target,
        action["save"],
        action["dc"],
        cond_type or action["name"],
        dc_mod=attacker.dc_mod,
        bonus_dice_eligible=False,
        advantage=reaction_save_advantage,
    )
    # The encounter-role overlay scales this the way it scales a weapon hit (check_resolution_attack
    # multiplies the final total by damage_mult): a Boss's wave must burn like a Boss. dc_mod already
    # rides the save above, so dropping the multiplier here would role-scale half the action.
    rolled_damage = max(0, int(dice_roll(action["damage"]).total * attacker.damage_mult))
    damage = rolled_damage // 2 if result.success else rolled_damage
    damage_result = SaveDamageResult(
        save_type=result.save_type,
        save_success=result.success,
        damage=damage,
        damage_type=action.get("damage_type", "none"),
        narrative_hint=result.narrative_hint,
        dramatic=result.dramatic,
        context=result.context,
    )
    # Announced here because the shared applicator refuses to publish an attack roll for save damage.
    await emit_or_publish(
        sink,
        session.room,
        E.DICE_ROLL,
        {
            "roll_type": "saving_throw",
            "save_type": result.save_type,
            "roll": result.roll,
            "total": result.total,
            "success": result.success,
            "dramatic": result.dramatic,
            "context": result.context,
            "damage": damage,
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
    )
    summary.update(_save_fields(result))
    summary["half_on_success"] = True
    summary["damage_halved"] = result.success
    if reaction_save_advantage and result.advantage_applied:
        summary["save_advantage"] = True
    if (item_save_source := target.save_advantages.get(result.save_type)) and result.advantage_applied:
        summary["save_advantage_source"] = item_save_source
    if cond_type is not None and not target.is_fallen:
        await _apply_condition_result(
            session,
            attacker,
            target,
            decl,
            cond_type,
            result,
            summary,
            state=state,
            conn=conn,
            concentration_break_mod=concentration_break_mod,
        )
    summary["actor_id"] = attacker.id
    summary["resolved"] = True
    summary["declaration_type"] = str(decl.type)
    return summary
