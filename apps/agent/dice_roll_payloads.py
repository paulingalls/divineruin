"""Build the DICE_ROLL wire payload from an already resolved roll."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from check_resolution import SkillCheckResult
    from check_resolution_save import SavingThrowResult
    from combat_resolution import DeathSaveResult
    from dice import DiceResult


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
    if attack_result.oath_justice is not None:
        payload["oath_justice"] = attack_result.oath_justice
    if attack_result.sneak_attack_dice is not None:
        payload.update(
            damage_type=attack_result.damage_type,
            sneak_attack_dice=attack_result.sneak_attack_dice,
            sneak_attack_raw_damage=attack_result.sneak_attack_raw_damage,
        )
    if attack_result.synergy_damage_type is not None:
        payload.update(
            synergy_damage=attack_result.synergy_damage, synergy_damage_type=attack_result.synergy_damage_type
        )
    if attack_result.synergy_clause_id is not None:
        payload["synergy_clause_id"] = attack_result.synergy_clause_id
    return payload


def build_skill_dice_roll_payload(
    result: SkillCheckResult, *, roll_type: str, success: bool | None, dramatic: bool, context: str, **fields: object
) -> dict:
    payload = {
        **fields,
        "roll_type": roll_type,
        "skill": result.skill,
        "roll": result.roll,
        "modifier": result.modifier,
        "total": result.total,
        "dramatic": dramatic,
        "context": context,
    }
    if success is not None:
        payload["success"] = success
    return payload


def build_saving_throw_dice_roll_payload(
    result: SavingThrowResult, *, roller_id: str, roll_type: str, **fields: object
) -> dict:
    receipt = result.receipt_fields(roller_id)
    del receipt["dc"]
    core = {key: receipt[key] for key in ("save_type", "roll", "total", "success")}
    return {**receipt, **fields, **core, "roll_type": roll_type, "modifier": result.modifier}


def build_narrative_dice_roll_payload(result: DiceResult) -> dict:
    kept_total = sum(result.rolls)
    return {
        "roll_type": "narrative",
        "notation": result.notation,
        "roll": kept_total,
        "modifier": result.total - kept_total,
        "total": result.total,
    }


def build_death_save_dice_roll_payload(result: DeathSaveResult, bonus_receipt: dict) -> dict:
    bonus = bonus_receipt["bonus"]
    return {
        **bonus_receipt,
        "roll_type": "death_save",
        "roll": result.roll,
        "modifier": bonus,
        "total": result.roll + bonus,
        "success": result.success,
        "critical_success": result.critical_success,
        "critical_failure": result.critical_failure,
        "total_successes": result.total_successes,
        "total_failures": result.total_failures,
        "dramatic": result.dramatic,
        "context": result.context,
    }
