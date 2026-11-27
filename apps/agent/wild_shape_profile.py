"""Authored Wild Shape profile shared by the agent and seed script."""

from typing import TypedDict

from catalog_parse import parse_int, parse_str

PRIMAL_SPELL = "primal_wild_shape"


class FormOption(TypedDict):
    creature_id: str
    min_level: int


class WildShapeProfile(TypedDict):
    stamina_cost: int
    forms: list[FormOption]


def positive_int(value: object, ctx: str) -> int:
    result = parse_int(value, ctx)
    if result < 1:
        raise ValueError(f"{ctx} must be positive")
    return result


def parse_profile(spell_id: str, data: dict) -> WildShapeProfile | None:
    if spell_id != PRIMAL_SPELL and "wild_shape" not in data:
        return None
    raw = data.get("wild_shape")
    ctx = f"spell {spell_id!r} wild_shape"
    if not isinstance(raw, dict):
        raise ValueError(f"{ctx} must be an object")
    stamina = positive_int(raw.get("stamina_cost"), f"{ctx}.stamina_cost")
    forms = raw.get("forms")
    if not isinstance(forms, list) or not forms:
        raise ValueError(f"{ctx}.forms must be a nonempty list")
    parsed: list[FormOption] = []
    seen = set()
    for form in forms:
        if not isinstance(form, dict):
            raise ValueError(f"{ctx}.forms entries must be objects")
        creature_id = parse_str(form.get("creature_id"), f"{ctx}.creature_id")
        if not creature_id.strip() or creature_id in seen:
            raise ValueError(f"{ctx} has an empty or repeated creature id {creature_id!r}")
        level = positive_int(form.get("min_level"), f"{ctx}.{creature_id}.min_level")
        seen.add(creature_id)
        parsed.append({"creature_id": creature_id, "min_level": level})
    return {"stamina_cost": stamina, "forms": parsed}
