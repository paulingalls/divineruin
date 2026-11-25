"""Restriction classification and shared condition-derived combat predicates."""

from condition_catalog import MARK_OF_JUSTICE
from condition_sources import no_hostile_source
from condition_voice_rules import auto_fail_hearing_perception, no_spoken_buffs
from conditions import get_condition_effects

NOT_ENFORCED: dict[str, dict[str, object]] = {
    "removed_from_combat": {"waits_on": "producer", "carriers": {"petrified": 1}},
    "immune_poison_disease": {"waits_on": "producer", "carriers": {"petrified": 1}},
    "damage_reduction": {"waits_on": "producer", "carriers": {"shielded": 1}},
    "no_approach_source": {"waits_on": "model", "model": "positioning"},
    "reduced_max_hp": {"waits_on": "producer", "carriers": {"wounded": 1}},
    "source_specific_penalty": {"waits_on": "producer", "carriers": {"cursed": 1}},
    "hallucinations": {"waits_on": "producer", "carriers": {"hollowed": 2}},
    "stat_drain": {"waits_on": "producer", "carriers": {"hollowed": 3}},
}


def _carriers(active_conditions: list[dict] | tuple[dict, ...], restriction: str) -> tuple[str, ...]:
    return tuple(
        condition["type"]
        for condition in active_conditions
        if restriction in get_condition_effects([condition]).restrictions
    )


def required_attack_sources(active_conditions: list[dict] | tuple[dict, ...]) -> tuple[str, ...]:
    sources = []
    for condition in active_conditions:
        if "must_target_source" not in get_condition_effects([condition]).restrictions:
            continue
        source = condition.get("source")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("Taunt source must be a nonempty actor ID")
        sources.append(source)
    return tuple(sources)


def mark_save_penalty(active_conditions: list[dict], originating_participant_id: str | None) -> int:
    if originating_participant_id is not None and any(
        c["type"] == MARK_OF_JUSTICE and c.get("source") == originating_participant_id for c in active_conditions
    ):
        return -2
    return 0


def damage_resistance_all(active_conditions: list[dict]) -> bool:
    return bool(_carriers(active_conditions, "damage_resistance_all"))


def saving_throw_advantage(active_conditions: list[dict]) -> bool:
    return bool(_carriers(active_conditions, "saving_throw_advantage"))


def immovable(active_conditions: list[dict]) -> bool:
    return bool(_carriers(active_conditions, "immovable"))


def incoming_advantage(active_conditions: list[dict] | tuple[dict, ...]) -> bool:
    return bool(_carriers(active_conditions, "incoming_advantage"))


def incoming_melee_advantage(active_conditions: list[dict] | tuple[dict, ...]) -> bool:
    return bool(_carriers(active_conditions, "incoming_melee_advantage"))


def incoming_melee_autocrit(active_conditions: list[dict] | tuple[dict, ...]) -> bool:
    return bool(_carriers(active_conditions, "incoming_melee_autocrit"))


def incoming_ranged_disadvantage(active_conditions: list[dict] | tuple[dict, ...]) -> bool:
    return bool(_carriers(active_conditions, "incoming_ranged_disadvantage"))


def incoming_disadvantage(active_conditions: list[dict] | tuple[dict, ...]) -> bool:
    return bool(_carriers(active_conditions, "incoming_disadvantage"))


def incoming_attack_modes(active_conditions: list[dict] | tuple[dict, ...], *, ranged: bool) -> tuple[bool, bool]:
    return (
        not ranged and incoming_melee_advantage(active_conditions),
        incoming_disadvantage(active_conditions) or (ranged and incoming_ranged_disadvantage(active_conditions)),
    )


def cannot_act(active_conditions: list[dict] | tuple[dict, ...]) -> tuple[str, ...]:
    """Condition types whose aggregated effects impose ``skip_phase``, in bearer order."""
    return _carriers(active_conditions, "skip_phase")


def declaration_costs(active_conditions: list[dict] | tuple[dict, ...]) -> tuple[str, ...]:
    return _carriers(active_conditions, "costs_declaration")


def ignores_structures(active_conditions: list[dict] | tuple[dict, ...]) -> bool:
    return bool(_carriers(active_conditions, "ignores_structures"))


def speed_zero(active_conditions: list[dict] | tuple[dict, ...]) -> tuple[str, ...]:
    return _carriers(active_conditions, "speed_0")


def speed_halved(active_conditions: list[dict] | tuple[dict, ...]) -> bool:
    return bool(_carriers(active_conditions, "speed_halved"))


def effective_speed(base_speed: float, active_conditions: list[dict]) -> float:
    return base_speed / 2 if speed_halved(active_conditions) else base_speed


def attack_consumed_conditions(
    active_conditions: list[dict] | tuple[dict, ...], *, spoken_buffs_eligible: bool = True
) -> tuple[str, ...]:
    return tuple(
        condition["type"]
        for condition in active_conditions
        if (condition["type"] != "inspired" or (spoken_buffs_eligible and not no_spoken_buffs(active_conditions)))
        and {"consumed_on_use", "one_time"} & get_condition_effects([condition]).restrictions
    )


RESTRICTION_ENFORCERS = {
    "damage_resistance_all": damage_resistance_all,
    "saving_throw_advantage": saving_throw_advantage,
    "immovable": immovable,
    "no_hostile_source": no_hostile_source,
    "must_target_source": required_attack_sources,
    "auto_fail_hearing_perception": auto_fail_hearing_perception,
    "no_spoken_buffs": no_spoken_buffs,
    "skip_phase": cannot_act,
    "incoming_advantage": incoming_advantage,
    "incoming_disadvantage": incoming_disadvantage,
    "incoming_melee_advantage": incoming_melee_advantage,
    "incoming_melee_autocrit": incoming_melee_autocrit,
    "incoming_ranged_disadvantage": incoming_ranged_disadvantage,
    "costs_declaration": declaration_costs,
    "speed_0": speed_zero,
    "speed_halved": speed_halved,
    "ignores_structures": ignores_structures,
    "consumed_on_use": attack_consumed_conditions,
    "one_time": attack_consumed_conditions,
}
ENFORCED = frozenset(RESTRICTION_ENFORCERS)
