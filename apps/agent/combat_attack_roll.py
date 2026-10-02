"""Shared rolling and persistence of an attack before impact."""

from dataclasses import asdict, replace

import check_resolution_attack
import combat_marks
import conditions
from dramatic import DramaticContext, evaluate_dramatic_context


def roll_attack(
    attacker,
    action: dict,
    target,
    *,
    target_ac_bonus: int = 0,
    enemies_remaining: int | None = None,
    is_first_attack_of_combat: bool = False,
    resolver=check_resolution_attack,
    combat_state=None,
) -> tuple:
    """Roll without applying HP changes; held reactions pause before impact."""
    attacker_data = {
        "attributes": attacker.attributes,
        "level": attacker.level,
        "conditions": attacker.conditions,
    }

    target_condition_ac = conditions.get_condition_effects(target.conditions).ac_modifier
    effective_ac = target.ac + target_ac_bonus + target_condition_ac
    attack_result = resolver.resolve_attack(
        attacker_data,
        action,
        effective_ac,
        target.hp_current,
        target_conditions=target.conditions,
        attack_mod=attacker.attack_mod
        + (combat_marks.attack_bonus(combat_state, attacker, target) if combat_state is not None else 0),
        damage_mult=attacker.damage_mult,
    )

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

    return attack_result, effective_ac


def serialize_roll(attack_result, effective_ac: int) -> dict:
    """Store the held roll in a JSON-native shape."""
    fields = asdict(attack_result)
    fields["consumed_conditions"] = list(fields["consumed_conditions"])
    return {"attack_result": fields, "effective_ac": effective_ac}


def deserialize_roll(data: dict) -> tuple:
    """The read-side inverse of ``serialize_roll`` — ``(AttackResult, effective_ac)``."""
    fields = dict(data["attack_result"])
    fields["consumed_conditions"] = tuple(fields.get("consumed_conditions") or ())
    return check_resolution_attack.AttackResult(**fields), data["effective_ac"]


def build_attack_dice_roll_payload(attacker, attack_result) -> dict:
    return {
        "roll_type": "attack",
        "attacker": attacker.name,
        "roll": attack_result.roll,
        "modifier": attack_result.attack_modifier,
        "total": attack_result.attack_total,
        "success": attack_result.hit,
        "narrative": attack_result.narrative_hint,
        "damage": attack_result.damage,
        "critical": attack_result.critical_success,
        "dramatic": attack_result.dramatic,
        "context": attack_result.context,
    }
