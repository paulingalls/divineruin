"""Restriction classification and shared condition-derived combat predicates."""

from conditions import get_condition_effects

ENFORCED = {
    "skip_phase",
    "incoming_advantage",
    "incoming_melee_advantage",
    "incoming_melee_autocrit",
    "incoming_ranged_disadvantage",
    "costs_declaration",
    "speed_0",
}

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


def incoming_attack_modes(active_conditions: list[dict] | tuple[dict, ...], *, ranged: bool) -> tuple[bool, bool]:
    restrictions = get_condition_effects(list(active_conditions)).restrictions
    return (
        not ranged and "incoming_melee_advantage" in restrictions,
        ranged and "incoming_ranged_disadvantage" in restrictions,
    )


def cannot_act(active_conditions: list[dict] | tuple[dict, ...]) -> tuple[str, ...]:
    """Condition types whose aggregated effects impose ``skip_phase``, in bearer order."""
    return tuple(
        condition["type"]
        for condition in active_conditions
        if "skip_phase" in get_condition_effects([condition]).restrictions
    )


def speed_zero(active_conditions: list[dict] | tuple[dict, ...]) -> tuple[str, ...]:
    return tuple(
        condition["type"]
        for condition in active_conditions
        if "speed_0" in get_condition_effects([condition]).restrictions
    )
