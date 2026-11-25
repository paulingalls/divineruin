from __future__ import annotations

from typing import TYPE_CHECKING

import abilities
import mentor_variants
from combat_order_riders import COORDINATED_ASSAULT as COORDINATED_ASSAULT
from combat_order_riders import DIRECT_STRIKE as DIRECT_STRIKE
from communication_voice_rules import can_hear
from mentor_variants import MentorVariant

if TYPE_CHECKING:
    from combat_state import CombatState

DEVASTATING_STRIKE = "warrior_devastating_strike"
BLADE_FLURRY = "rogue_blade_flurry"
SINGLE_TARGET_WEAPON_ABILITIES = (DEVASTATING_STRIKE, BLADE_FLURRY)
CLEAVING_BLOW = "warrior_cleaving_blow"
WHIRLWIND = "warrior_whirlwind"
MULTI_TARGET_WEAPON_ABILITIES = (CLEAVING_BLOW, WHIRLWIND)
SHIELD_BASH = "warrior_shield_bash"
DIRTY_TRICK = "rogue_dirty_trick"
TAUNT = "warrior_taunt"
WAR_CRY = "warrior_war_cry"
SHIELD_BASH_RIDER = "shield_bash"
CRIPPLING_STRIKE = "rogue_crippling_strike"
CRIPPLING_STRIKE_RIDER = "crippling_strike"
EXPLOIT_WEAKNESS = "rogue_exploit_weakness"
CUNNING_ACTION = "rogue_cunning_action"
CUNNING_RIDERS = ("dash", "hide", "disengage")
RECKLESS_ASSAULT_RIDER = "reckless_assault"
ELECTIVE_ATTACK_RIDERS = {
    "precision_strike": "warrior_precision_strike",
    RECKLESS_ASSAULT_RIDER: "warrior_reckless_assault",
}

ELECTIVE_RIDER_ABILITIES = frozenset((*ELECTIVE_ATTACK_RIDERS.values(), CRIPPLING_STRIKE))

SECOND_WIND = "warrior_second_wind"
RALLYING_SHOUT = "warrior_rallying_shout"

MARSHAL_ORDERS = frozenset(
    {
        DIRECT_STRIKE,
        "marshal_reposition",
        COORDINATED_ASSAULT,
        "marshal_field_medic_order",
        "marshal_sacrifice_play",
    }
)

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
        or ability.id
        in (SECOND_WIND, EXPLOIT_WEAKNESS, *SINGLE_TARGET_WEAPON_ABILITIES, *MULTI_TARGET_WEAPON_ABILITIES)
        or ability.id in MARSHAL_ORDERS
    )


def war_cry_targets(state: CombatState) -> list[str]:
    return [
        participant.id
        for participant in state.participants
        if not participant.is_ally
        and not participant.is_structure
        and not participant.is_fallen
        and can_hear(state, participant.id)
    ]


def attack_recipe(ability_id: str) -> dict[str, str | list[str]] | None:
    if ability_id == CUNNING_ACTION:
        return {"kind": "attack", "riders": list(CUNNING_RIDERS)}
    if ability_id == SHIELD_BASH:
        return {"kind": "attack", "rider": SHIELD_BASH_RIDER}
    if ability_id == CRIPPLING_STRIKE:
        return {"kind": "attack", "rider": CRIPPLING_STRIKE_RIDER}
    for rider, elective_id in ELECTIVE_ATTACK_RIDERS.items():
        if ability_id == elective_id:
            return {"kind": "attack", "rider": rider}
    return None


def require_rally_target(actor_id: str, target_id: str | None, eligible_ids: set[str]) -> None:
    if target_id is None or target_id == actor_id or target_id not in eligible_ids:
        raise ValueError("Rallying Shout requires one standing ally.")
