"""Restriction classification and shared condition-derived combat predicates."""

from conditions import get_condition_effects

NOT_ENFORCED: dict[str, dict[str, object]] = {
    "removed_from_combat": {"waits_on": "producer", "carriers": {"petrified"}},
    "damage_resistance_all": {"waits_on": "producer", "carriers": {"petrified"}},
    "immune_poison_disease": {"waits_on": "producer", "carriers": {"petrified"}},
    "damage_reduction": {"waits_on": "producer", "carriers": {"shielded"}},
    "no_approach_source": {"waits_on": "model", "model": "positioning"},
    "no_hostile_source": {"waits_on": "producer", "carriers": {"charmed"}},
    "auto_fail_hearing_perception": {"waits_on": "producer", "carriers": {"deafened"}},
    "no_spoken_buffs": {"waits_on": "producer", "carriers": {"deafened"}},
    "reduced_max_hp": {"waits_on": "producer", "carriers": {"wounded"}},
    "source_specific_penalty": {"waits_on": "producer", "carriers": {"cursed"}},
    "hallucinations": {"waits_on": "producer", "carriers": {"hollowed"}},
    "stat_drain": {"waits_on": "producer", "carriers": {"hollowed"}},
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


def attack_consumed_conditions(active_conditions: list[dict] | tuple[dict, ...]) -> tuple[str, ...]:
    return tuple(
        condition["type"]
        for condition in active_conditions
        if {"consumed_on_use", "one_time"} & get_condition_effects([condition]).restrictions
    )


RESTRICTION_ENFORCERS = {
    "skip_phase": cannot_act,
    "incoming_advantage": incoming_advantage,
    "incoming_melee_advantage": incoming_melee_advantage,
    "incoming_melee_autocrit": incoming_melee_autocrit,
    "incoming_ranged_disadvantage": incoming_ranged_disadvantage,
    "costs_declaration": declaration_costs,
    "speed_0": speed_zero,
    "consumed_on_use": attack_consumed_conditions,
    "one_time": attack_consumed_conditions,
}
ENFORCED = frozenset(RESTRICTION_ENFORCERS)
