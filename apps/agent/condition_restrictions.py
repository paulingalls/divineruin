"""Restriction classification and shared condition-derived combat predicates."""

from conditions import get_condition_effects

NOT_ENFORCED: dict[str, str] = {
    "removed_from_combat": "No Petrified producer exists.",
    "damage_resistance_all": "Resistance needs a damage-type resistance model.",
    "immune_poison_disease": "No Petrified producer exists.",
    "damage_reduction": "Shield reactions use combat_reaction_effect instead.",
    "no_approach_source": "Phase combat has no positioning.",
    "no_hostile_source": "Target refusal needs the condition source.",
    "auto_fail_hearing_perception": "No in-combat producer or perception consumer exists.",
    "no_spoken_buffs": "No in-combat producer or spoken-buff consumer exists.",
    "reduced_max_hp": "This belongs to the rest-scoped HP model.",
    "source_specific_penalty": "No curse source defines a penalty.",
    "consumed_on_use": "Bonus dice consume elsewhere; Shaken remains owed.",
    "one_time": "Shaken has no bonus die and its consumption remains owed.",
    "hallucinations": "The Hollowed narrative model is outside combat mechanics.",
    "stat_drain": "The Hollowed stat-drain model is outside combat mechanics.",
}


def _carriers(active_conditions: list[dict] | tuple[dict, ...], restriction: str) -> tuple[str, ...]:
    return tuple(
        condition["type"]
        for condition in active_conditions
        if restriction in get_condition_effects([condition]).restrictions
    )


def incoming_advantage(active_conditions: list[dict] | tuple[dict, ...]) -> bool:
    return bool(_carriers(active_conditions, "incoming_advantage"))


def incoming_melee_advantage(active_conditions: list[dict] | tuple[dict, ...]) -> bool:
    return bool(_carriers(active_conditions, "incoming_melee_advantage"))


def incoming_melee_autocrit(active_conditions: list[dict] | tuple[dict, ...]) -> bool:
    return bool(_carriers(active_conditions, "incoming_melee_autocrit"))


def incoming_ranged_disadvantage(active_conditions: list[dict] | tuple[dict, ...]) -> bool:
    return bool(_carriers(active_conditions, "incoming_ranged_disadvantage"))


def incoming_attack_modes(active_conditions: list[dict] | tuple[dict, ...], *, ranged: bool) -> tuple[bool, bool]:
    return (
        not ranged and incoming_melee_advantage(active_conditions),
        ranged and incoming_ranged_disadvantage(active_conditions),
    )


def cannot_act(active_conditions: list[dict] | tuple[dict, ...]) -> tuple[str, ...]:
    """Condition types whose aggregated effects impose ``skip_phase``, in bearer order."""
    return _carriers(active_conditions, "skip_phase")


def declaration_costs(active_conditions: list[dict] | tuple[dict, ...]) -> tuple[str, ...]:
    return _carriers(active_conditions, "costs_declaration")


def speed_zero(active_conditions: list[dict] | tuple[dict, ...]) -> tuple[str, ...]:
    return _carriers(active_conditions, "speed_0")


RESTRICTION_ENFORCERS = {
    "skip_phase": cannot_act,
    "incoming_advantage": incoming_advantage,
    "incoming_melee_advantage": incoming_melee_advantage,
    "incoming_melee_autocrit": incoming_melee_autocrit,
    "incoming_ranged_disadvantage": incoming_ranged_disadvantage,
    "costs_declaration": declaration_costs,
    "speed_0": speed_zero,
}
ENFORCED = frozenset(RESTRICTION_ENFORCERS)
