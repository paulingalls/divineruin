"""Resolve and persist the three contested social reactions."""

from __future__ import annotations

import random

import rules_engine

EFFECTS = {
    "marshal_countermand": "command_countered",
    "spy_plausible_deniability": "accusation_dismissed",
    "diplomat_objection": "action_hesitated",
}
_CANCELS_MARK = frozenset({"command_countered", "accusation_dismissed"})
_ATTRIBUTES = {
    "marshal_countermand": ("charisma", "charisma"),
    "spy_plausible_deniability": ("charisma", "wisdom"),
    "diplomat_objection": ("charisma", "wisdom"),
}
_RESULT_KEYS = frozenset({"ability_id", "reactor_total", "opposer_total", "success"})


def _attribute(participant, name: str) -> int:
    try:
        score = participant.attributes[name]
    except KeyError as exc:
        raise ValueError(f"participant {participant.id!r} has no {name!r} attribute for reaction contest") from exc
    if not isinstance(score, int):
        raise ValueError(f"participant {participant.id!r} has invalid {name!r} attribute {score!r}")
    return score


def _validate_stored(raw: object, ability_id: str) -> dict:
    if not isinstance(raw, dict) or set(raw) != _RESULT_KEYS:
        raise ValueError(f"stored reaction contest is malformed: {raw!r}")
    if raw["ability_id"] != ability_id:
        raise ValueError(
            f"stored reaction contest belongs to {raw['ability_id']!r}, not closing reaction {ability_id!r}"
        )
    if type(raw["reactor_total"]) is not int or type(raw["opposer_total"]) is not int:
        raise ValueError(f"stored reaction contest has non-integer totals: {raw!r}")
    if type(raw["success"]) is not bool:
        raise ValueError(f"stored reaction contest has non-boolean success: {raw!r}")
    if raw["success"] != (raw["reactor_total"] > raw["opposer_total"]):
        raise ValueError(f"stored reaction contest outcome contradicts its totals: {raw!r}")
    return raw


def resolve_or_reuse(state, head: dict, spend: dict, *, rng=None) -> dict | None:
    ability_id = spend["ability_id"]
    if ability_id not in EFFECTS:
        return None
    if "reaction_contest" in head:
        return _validate_stored(head["reaction_contest"], ability_id)

    reactor = state.get_participant(spend["actor_id"])
    opposer = state.get_participant(head["actor_id"])
    if reactor is None or opposer is None:
        raise ValueError(f"reaction contest requires reactor {spend['actor_id']!r} and opposer {head['actor_id']!r}")
    reactor_attr, opposer_attr = _ATTRIBUTES[ability_id]
    roller = rng or random
    reactor_total = roller.randint(1, 20) + rules_engine.attribute_modifier(_attribute(reactor, reactor_attr))
    opposer_total = roller.randint(1, 20) + rules_engine.attribute_modifier(_attribute(opposer, opposer_attr))
    result = {
        "ability_id": ability_id,
        "reactor_total": reactor_total,
        "opposer_total": opposer_total,
        "success": reactor_total > opposer_total,
    }
    head["reaction_contest"] = result
    return result


def _won_effect(head: dict) -> str | None:
    result = head.get("reaction_contest")
    if not isinstance(result, dict) or result.get("success") is not True:
        return None
    return EFFECTS.get(str(result.get("ability_id")))


def mark_cancelled(head: dict) -> bool:
    return _won_effect(head) in _CANCELS_MARK


def hesitated(head: dict) -> bool:
    return _won_effect(head) == "action_hesitated"
