"""Resolve and persist the three contested social reactions."""

from __future__ import annotations

import random

import reaction_spend
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


def _validate_stored(raw: object, ability_id: object) -> dict:
    if not isinstance(raw, dict) or set(raw) != _RESULT_KEYS:
        raise ValueError(f"stored reaction contest is malformed: {raw!r}")
    if not isinstance(raw["ability_id"], str):
        raise ValueError(f"stored reaction contest has non-string ability id: {raw!r}")
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
    contests = head.setdefault("reaction_contests", {})
    if spend["actor_id"] in contests:
        return _validate_stored(contests[spend["actor_id"]], ability_id)

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
    contests[spend["actor_id"]] = result
    return result


def normalize_held_actions(held_actions: list[dict], reactions_available: dict[str, dict]) -> list[dict]:
    normalized = []
    for raw_head in held_actions:
        head = dict(raw_head)
        if "reaction_contest" in head and "reaction_contests" in head:
            raise ValueError(f"held reaction contest {head['seq']!r} carries both singular and plural storage")
        if "reaction_contest" in head:
            result = head["reaction_contest"]
            ability_id = result.get("ability_id") if isinstance(result, dict) else None
            validated = _validate_stored(result, ability_id)
            candidates = [
                actor_id
                for actor_id, spend in reactions_available.items()
                if reaction_spend.is_spent(spend)
                and spend["held_seq"] == head["seq"]
                and spend["ability_id"] == ability_id
            ]
            if len(candidates) != 1:
                raise ValueError(
                    f"held reaction contest {head['seq']!r} has {len(candidates)} matching reactors; expected one"
                )
            head["reaction_contests"] = {candidates[0]: validated}
            del head["reaction_contest"]
        normalized.append(head)
    return normalized


def _won_effects(head: dict) -> list[tuple[str, str]]:
    """(reactor id, effect) for every stored contest the reactor won."""
    contests = head.get("reaction_contests", {})
    if not isinstance(contests, dict):
        raise ValueError(f"stored reaction contests are malformed: {contests!r}")
    won = []
    for actor_id, result in contests.items():
        ability_id = result.get("ability_id") if isinstance(result, dict) else None
        validated = _validate_stored(result, ability_id)
        if validated["success"] and validated["ability_id"] in EFFECTS:
            won.append((actor_id, EFFECTS[validated["ability_id"]]))
    return won


def mark_cancelled(head: dict) -> bool:
    return any(effect in _CANCELS_MARK for _, effect in _won_effects(head))


def hesitation_reason(head: dict) -> str | None:
    """Name the reactor whose winning Objection cost the held action, or None if none did."""
    return next(
        (f"Objection raised by {actor_id}" for actor_id, effect in _won_effects(head) if effect == "action_hesitated"),
        None,
    )


def hesitated(head: dict) -> bool:
    return hesitation_reason(head) is not None
