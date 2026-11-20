"""Encounter facts recorded when combat damage settles."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from check_resolution_attack import AttackResult

if TYPE_CHECKING:
    from combat_damage_results import AutomaticDamageResult, SaveDamageResult
    from combat_participant import CombatParticipant
    from combat_state import CombatState

ZHAEL_THREADED_BLADE = "zhael_threaded_blade"


class EncounterFacts(TypedDict):
    ally_downers: list[str]
    attacked: list[str]
    misses: dict[str, list[str]]
    once_spent: dict[str, list[str]]


def empty() -> EncounterFacts:
    return {"ally_downers": [], "attacked": [], "misses": {}, "once_spent": {}}


def _is_id(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _ids(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not all(_is_id(item) for item in value):
        raise ValueError(f"encounter_facts.{field} requires a list of nonblank string IDs")
    return list(value)


def _id_map(value: object, field: str) -> dict[str, list[str]]:
    if not isinstance(value, dict) or not all(_is_id(key) for key in value):
        raise ValueError(f"encounter_facts.{field} requires an object keyed by nonblank string IDs")
    return {key: _ids(ids, f"{field}.{key}") for key, ids in value.items()}


def validate(value: object) -> EncounterFacts:
    if not isinstance(value, dict) or value.keys() != EncounterFacts.__required_keys__:
        raise ValueError("encounter_facts requires exactly ally_downers, attacked, misses, and once_spent")
    return {
        "ally_downers": _ids(value["ally_downers"], "ally_downers"),
        "attacked": _ids(value["attacked"], "attacked"),
        "misses": _id_map(value["misses"], "misses"),
        "once_spent": _id_map(value["once_spent"], "once_spent"),
    }


def _remember(ids: list[str], participant_id: str) -> None:
    if participant_id not in ids:
        ids.append(participant_id)


def record_landing(
    state: CombatState | None,
    attacker: CombatParticipant,
    target: CombatParticipant,
    result: AttackResult | SaveDamageResult | AutomaticDamageResult,
    hp_before: int,
) -> None:
    if state is None:
        return
    facts = state.encounter_facts
    if hp_before > 0 and target.is_ally and target.is_fallen:
        _remember(facts["ally_downers"], attacker.id)
    if isinstance(result, AttackResult):
        _remember(facts["attacked"], target.id)
        if not result.hit:
            _remember(facts["misses"].setdefault(attacker.id, []), target.id)
        if result.synergy_clause_id == ZHAEL_THREADED_BLADE:
            _remember(facts["once_spent"].setdefault(ZHAEL_THREADED_BLADE, []), attacker.id)
