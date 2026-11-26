"""Rolled damage results that land through combat_damage, and their JSON-native freeze."""

from dataclasses import asdict, dataclass

import check_resolution_attack
from combat_order_riders import COORDINATED_ASSAULT_NAME, DIRECT_STRIKE_NAME, SACRIFICE_PLAY_NAME


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


def freeze_blow(action, attack_result, effective_ac) -> dict:
    """A rolled blow in a JSON-native shape, so a held save can resume landing it."""
    fields = asdict(attack_result)
    if "consumed_conditions" in fields:
        fields["consumed_conditions"] = list(fields["consumed_conditions"])
    return {"action": action, "kind": type(attack_result).__name__, "fields": fields, "effective_ac": effective_ac}


def thaw_blow(data: dict):
    kinds = {
        cls.__name__: cls for cls in (check_resolution_attack.AttackResult, SaveDamageResult, AutomaticDamageResult)
    }
    fields = dict(data["fields"])
    if "consumed_conditions" in fields:
        fields["consumed_conditions"] = tuple(fields["consumed_conditions"])
    return data["action"], kinds[data["kind"]](**fields), data["effective_ac"]


def attack_fields(attack_result: check_resolution_attack.AttackResult, effective_ac: int, action: dict) -> dict:
    fields: dict = dict(
        hit=attack_result.hit,
        roll=attack_result.roll,
        attack_total=attack_result.attack_total,
        target_ac=effective_ac,
        critical=attack_result.critical_success,
        sneak_attack_dice=attack_result.sneak_attack_dice,
        sneak_attack_raw_damage=attack_result.sneak_attack_raw_damage,
        bonus_damage=attack_result.bonus_damage,
        bonus_damage_type=attack_result.bonus_damage_type,
        rider_damage=attack_result.rider_damage,
        rider_damage_type=attack_result.rider_damage_type,
        rider_ignores_resistance=attack_result.rider_ignores_resistance,
        synergy_damage=attack_result.synergy_damage,
        synergy_damage_type=attack_result.synergy_damage_type,
        synergy_clause_id=attack_result.synergy_clause_id,
        synergy_ac_bonus=attack_result.synergy_ac_bonus,
        synergy_ac_clause_id=attack_result.synergy_ac_clause_id,
        mortaen_ac_bonus=attack_result.mortaen_ac_bonus,
        mortaen_ac_clause_id=attack_result.mortaen_ac_clause_id,
        orenthel_ac_bonus=attack_result.orenthel_ac_bonus,
        orenthel_ac_clause_id=attack_result.orenthel_ac_clause_id,
        war_songs_bonus=attack_result.war_songs_bonus,
        war_songs_clause_id=attack_result.war_songs_clause_id,
        consumed_conditions=attack_result.consumed_conditions,
    )
    if attack_result.attack_disadvantage_source is not None:
        fields["attack_disadvantage_source"] = attack_result.attack_disadvantage_source
    if attack_result.order_rider is not None:
        fields["order_rider"] = {
            "order_id": attack_result.order_rider["order_id"],
            "name": DIRECT_STRIKE_NAME,
            "dice": attack_result.order_damage_dice,
            "raw_damage": attack_result.order_raw_damage,
        }
        if attack_result.hit and action.get("bonus_damage") is not None:
            fields["bonus_damage_source"] = action["name"]
    if (coordinated := attack_result.coordinated_rider) is not None:
        order: dict = dict(
            order_id=coordinated["order_id"], name=COORDINATED_ASSAULT_NAME, source_id=coordinated["source_id"]
        )
        if attack_result.pincer_dice is not None:
            order.update(dice=attack_result.pincer_dice, raw_damage=attack_result.pincer_raw_damage)
        fields["coordinated_assault"] = order
    if (sacrifice := attack_result.sacrifice_rider) is not None:
        fields["sacrifice_play"] = {
            "order_id": sacrifice["order_id"],
            "name": SACRIFICE_PLAY_NAME,
            "source_id": sacrifice["source_id"],
        }
    return fields
