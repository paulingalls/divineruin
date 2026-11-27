"""Damage and AC changes made by self-protective reactions."""

from dataclasses import replace

import conditions
import dice
import temp_hp
from check_resolution import D20Roll
from check_resolution_attack import AttackResult
from combat_attack_roll import deserialize_roll, serialize_roll
from combat_damage_affinity import with_landed_damage
from combat_damage_results import AutomaticDamageResult, SaveDamageResult
from combat_participant import BARK_SKIN_AC_BONUS, CombatParticipant
from rules_engine import attribute_modifier

BRACE = "warrior_brace_for_impact"
SHIELD_SPELL = "mage_shield_spell"
THOUGHT_SHIELD = "whisper_thought_shield"

_DAMAGE_PARTS = ("rider_damage", "bonus_damage", "synergy_damage")


def brace(head: dict, target: CombatParticipant) -> tuple[int, int]:
    result, held_ac = deserialize_roll(head["roll"])
    reduction = max(0, dice.roll("1d6").total + attribute_modifier(target.attributes["constitution"]))
    damage = max(0, result.damage - reduction)
    parts = {name: getattr(result, name) for name in _DAMAGE_PARTS}
    remaining = max(0, sum(parts.values()) - damage)
    for name, amount in parts.items():
        removed = min(remaining, amount)
        parts[name] -= removed
        remaining -= removed
    held = with_landed_damage(
        result,
        damage,
        target.hp_current,
        temporary=temp_hp.player_pool(target),
        hp_floor=conditions.damage_hp_floor(target.conditions),
        **parts,
    )
    head["roll"] = serialize_roll(held, held_ac)
    return reduction, result.damage - held.damage


def halve_psychic(
    action: dict, result: AttackResult | SaveDamageResult | AutomaticDamageResult, target: CombatParticipant
) -> tuple[dict, AttackResult | SaveDamageResult | AutomaticDamageResult, int]:
    def reduced(amount: int, kind: str | None) -> int:
        return amount // 2 if kind == "psychic" else amount

    if not isinstance(result, AttackResult):
        damage = reduced(result.damage, result.damage_type)
        return action, replace(result, damage=damage), result.damage - damage

    parts = {name: reduced(getattr(result, name), getattr(result, name + "_type")) for name in _DAMAGE_PARTS}
    primary = result.damage - sum(getattr(result, name) for name in _DAMAGE_PARTS)
    if components := action.get("damage_components"):
        components = [{**part, "damage": reduced(part["damage"], part["damage_type"])} for part in components]
        action = {**action, "damage_components": components}
        damage = sum(part["damage"] for part in components)
    else:
        damage = reduced(primary, result.damage_type)
    damage = max(0, damage + sum(parts.values()))
    return (
        action,
        with_landed_damage(
            result,
            damage,
            target.hp_current,
            temporary=temp_hp.player_pool(target),
            hp_floor=conditions.damage_hp_floor(target.conditions),
            **parts,
        ),
        result.damage - damage,
    )


def halve(head: dict, target) -> None:
    """Halve the held blow against live HP so its summary and impact agree after a reload.

    The dice event precedes the post-roll reaction window and still describes the original roll.
    """
    result, held_ac = deserialize_roll(head["roll"])
    halved = with_landed_damage(
        result,
        result.damage // 2,
        target.hp_current,
        temporary=temp_hp.player_pool(target),
        hp_floor=conditions.damage_hp_floor(target.conditions),
        bonus_damage=result.bonus_damage // 2,
        rider_damage=result.rider_damage // 2,
        synergy_damage=result.synergy_damage // 2,
    )
    head["roll"] = serialize_roll(halved, held_ac)


def apply_bark_skin(head: dict, target: CombatParticipant) -> None:
    result, held_ac = deserialize_roll(head["roll"])
    if not D20Roll(result.attack_modifier, held_ac).evaluate(result.roll).success:
        raise ValueError("Bark Skin expected a held hit that reached the original AC")

    raised_ac = held_ac + BARK_SKIN_AC_BONUS
    verdict = D20Roll(result.attack_modifier, raised_ac).evaluate(result.roll)
    result = replace(result, target_ac=raised_ac, narrative_hint=verdict.narrative_hint)
    if not verdict.success:
        result = with_landed_damage(
            replace(result, hit=False),
            0,
            target.hp_current,
            critical_success=False,
            bonus_damage=0,
            bonus_damage_type=None,
            rider_damage=0,
            rider_damage_type=None,
            rider_ignores_resistance=False,
            sneak_attack_dice=None,
            sneak_attack_raw_damage=0,
            synergy_damage=0,
            synergy_damage_type=None,
            synergy_clause_id=None,
            order_rider=None,
            order_damage_dice=None,
            order_raw_damage=0,
            coordinated_rider=None,
            pincer_dice=None,
            pincer_raw_damage=0,
            sacrifice_rider=None,
        )
    target.bark_skin_active = True
    head["roll"] = serialize_roll(result, raised_ac)
