"""Restriction classification and shared condition-derived combat predicates."""

from conditions import get_condition_effects

ENFORCED = {"skip_phase", "incoming_advantage", "incoming_melee_autocrit"}

NOT_ENFORCED: dict[str, str] = {
    "speed_0": "Phase combat has no positioning.",
    "costs_declaration": "No stand-up or escape declaration kind exists.",
    "incoming_melee_advantage": "No content or producer applies Prone; follow-on work.",
    "incoming_ranged_disadvantage": "No content or producer applies Prone; follow-on work.",
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


def cannot_act(active_conditions: list[dict] | tuple[dict, ...]) -> tuple[str, ...]:
    """Condition types whose aggregated effects impose ``skip_phase``, in bearer order."""
    return tuple(
        condition["type"]
        for condition in active_conditions
        if "skip_phase" in get_condition_effects([condition]).restrictions
    )
