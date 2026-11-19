"""Shared rolling and persistence of an attack before impact."""

from dataclasses import asdict, replace

import check_resolution_attack
import combat_marks
import combat_spatial
import condition_voice_rules
import conditions
from dramatic import DramaticContext, evaluate_dramatic_context

BEACON = "Beacon"


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
    weapon_attack: bool = True,
) -> tuple:
    """Roll without applying HP changes; held reactions pause before impact."""
    attacker_data, effective_ac, attack_mod = attack_roll_inputs(
        attacker, target, target_ac_bonus, combat_state, action, weapon_attack=weapon_attack
    )
    attack_result = resolver.resolve_attack(
        attacker_data,
        action,
        effective_ac,
        target.hp_current,
        target_conditions=target.conditions,
        attack_mod=attack_mod,
        damage_mult=attacker.damage_mult,
    )
    spend_sneak_attack(attacker, combat_state, attack_result)

    return promote_attack(attack_result, enemies_remaining, is_first_attack_of_combat), effective_ac


def attack_roll_inputs(attacker, target, target_ac_bonus, combat_state, action, *, weapon_attack=True):
    """The attacker data, effective AC and to-hit bonus a d20 attack is prepared from.

    Only reads state: a rogue's Sneak Attack allowance is offered here and spent by
    ``spend_sneak_attack`` after the attack is finished, so a held roll never spends it early."""
    attacker_data = {
        "attributes": attacker.attributes,
        "level": attacker.level,
        "conditions": attacker.conditions,
    }

    if weapon_attack and attacker.type == "player" and attacker.archetype_id == "rogue":
        if combat_state is None:
            raise ValueError("rogue weapon attack requires combat state")
        attacker_data["sneak_attack_available"] = attacker.sneak_attack_round != combat_state.round_number
        advantage, disadvantage = check_resolution_attack.attack_modes(attacker_data, action, target.conditions)
        if attacker_data["sneak_attack_available"] and not (advantage and not disadvantage):
            spatial = combat_spatial.require_spatial(combat_state)
            attacker_data["sneak_attack_adjacent_ally"] = any(
                ally.id not in (attacker.id, target.id)
                and ally.is_ally
                and not ally.is_fallen
                and not ally.is_dead
                and combat_spatial.inside(
                    combat_spatial.position(spatial, ally.id), combat_spatial.position(spatial, target.id), 5
                )
                for ally in combat_state.participants
            )
    attacker_data = condition_voice_rules.roll_data(attacker_data, combat_state, attacker.id)
    target_condition_ac = conditions.get_condition_effects(target.conditions).ac_modifier
    effective_ac = target.ac + target_ac_bonus + target_condition_ac
    attack_mod = attacker.attack_mod
    if combat_state is not None:
        attack_mod += combat_marks.attack_bonus(combat_state, attacker, target)
        if (
            attacker.hollow is not None
            and target.orenthel_beacon
            and target.id not in combat_state.beacon_attacks.get(attacker.id, ())
        ):
            attacker_data["attack_disadvantage_source"] = BEACON
    return attacker_data, effective_ac, attack_mod


def spend_sneak_attack(attacker, combat_state, attack_result) -> None:
    """Mark this round's Sneak Attack used once a finished attack actually added its dice."""
    if combat_state is not None and attack_result.sneak_attack_dice is not None:
        attacker.sneak_attack_round = combat_state.round_number


def record_beacon_attack(combat_state, attacker, target, attack_result: check_resolution_attack.AttackResult) -> None:
    if combat_state is None or attack_result.attack_disadvantage_source != BEACON:
        return
    targets = combat_state.beacon_attacks.setdefault(attacker.id, [])
    if target.id not in targets:
        targets.append(target.id)


def promote_attack(attack_result, enemies_remaining, is_first_attack_of_combat):
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

    return attack_result


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
    payload = {
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
    if attack_result.sneak_attack_dice is not None:
        payload.update(
            damage_type=attack_result.damage_type,
            sneak_attack_dice=attack_result.sneak_attack_dice,
            sneak_attack_raw_damage=attack_result.sneak_attack_raw_damage,
        )
    return payload


def held_reaction_ac(head: dict) -> int:
    contribution = head.get("reaction_ac_bonus")
    if type(contribution) is not int or contribution not in (0, 2):
        raise ValueError(
            "Rolled held action requires explicit valid reaction AC contribution; reset/reseed old snapshots"
        )
    return contribution
