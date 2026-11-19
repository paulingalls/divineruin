"""Rolled damage results that land through combat_damage, and their JSON-native freeze."""

from dataclasses import asdict, dataclass

import check_resolution_attack


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
