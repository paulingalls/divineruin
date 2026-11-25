from __future__ import annotations

import abilities
import mentor_variants
from mentor_variants import MentorVariant

DEVASTATING_STRIKE = "warrior_devastating_strike"
SHIELD_BASH = "warrior_shield_bash"
SHIELD_BASH_RIDER = "shield_bash"
CUNNING_ACTION = "rogue_cunning_action"
CUNNING_RIDERS = ("dash", "hide", "disengage")

SECOND_WIND = "warrior_second_wind"
RALLYING_SHOUT = "warrior_rallying_shout"

DeclaredAbility = tuple[abilities.Ability, MentorVariant | None]


def declared_ability(action: str | None) -> DeclaredAbility | None:
    if action is None:
        return None
    try:
        return abilities.get_ability(action), None
    except ValueError:
        pass
    try:
        variant = mentor_variants.get_mentor_variant(action)
    except ValueError:
        return None
    return abilities.get_ability(variant.ability_id), variant


def combat_ability(ability: abilities.Ability) -> bool:
    return (
        ability.spell_id is not None
        or ability.applies_condition is not None
        or ability.id in (SECOND_WIND, DEVASTATING_STRIKE)
    )


def attack_recipe(ability_id: str) -> dict[str, str | list[str]] | None:
    if ability_id == CUNNING_ACTION:
        return {"kind": "attack", "riders": list(CUNNING_RIDERS)}
    if ability_id == SHIELD_BASH:
        return {"kind": "attack", "rider": SHIELD_BASH_RIDER}
    return None


def require_rally_target(actor_id: str, target_id: str | None, eligible_ids: set[str]) -> None:
    if target_id is None or target_id == actor_id or target_id not in eligible_ids:
        raise ValueError("Rallying Shout requires one standing ally.")
