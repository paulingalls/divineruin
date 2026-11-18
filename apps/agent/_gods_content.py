"""Validated, process-cached patron content shared by agent consumers."""

from __future__ import annotations

import functools
import json
import math
import re
from pathlib import Path

_GODS_JSON_PATH = Path(__file__).resolve().parents[2] / "content" / "gods.json"
_CONTENT = _GODS_JSON_PATH.parent


@functools.cache
def archetype_ids() -> frozenset[str]:
    rows = json.loads((_CONTENT / "archetypes.json").read_text())
    ids = [_text(row.get("id"), f"archetypes[{i}].id") for i, row in enumerate(rows)]
    if not ids or len(ids) != len(set(ids)):
        _fail("archetypes", "expected nonempty unique roster")
    return frozenset(ids)


@functools.cache
def engine_implementations() -> dict[str, str]:
    registry = _object(json.loads((_CONTENT / "engine_implementations.json").read_text()), "engine_implementations")
    if not registry:
        _fail("engine_implementations", "expected nonempty registry")
    for key, target in registry.items():
        _text(key, "engine_implementations.id")
        _text(target, f"engine_implementations.{key}")
    return registry


_TIERS = {"acknowledged", "devoted", "exalted"}
_MODIFIERS = {
    "flickering_damage_dice": ({"arcane_flickering"}, "positive_integer"),
    "generation_delta": (
        {"combat_aid", "natural_ground", "hidden_or_stealthed", "unvisited_location"},
        "negative_integer",
    ),
    "ward_penalty_immunity": ({"inside_active_veil_ward"}, "true"),
    "primal_multiplier_steps": ({"primal_on_natural_ground"}, "negative_integer"),
    "generation_override": ({"healing", "target_at_zero_hp"}, "nonnegative_integer"),
    "generation_multiplier": ({"wrongdoer_target"}, "positive_fraction_at_most_one"),
    "echo_roll_choice": ({"overreach"}, "integer_at_least_two"),
}


def _fail(path: str, reason: str) -> None:
    raise ValueError(f"{path}: {reason}")


def _object(value: object, path: str, keys: set[str] | None = None) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected object")
    if keys is not None:
        for key in sorted(keys - value.keys()):
            _fail(f"{path}.{key}", "required field")
        for key in sorted(value.keys() - keys):
            _fail(f"{path}.{key}", "unknown field")
    return value


def _text(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path}: expected nonblank string")
    return value


def _modifier(value: object, path: str) -> None:
    modifier = _object(value, path, {"kind", "applies_to", "value"})
    kind = _text(modifier["kind"], f"{path}.kind")
    if kind not in _MODIFIERS:
        _fail(f"{path}.kind", "unknown modifier kind")
    predicates, rule = _MODIFIERS[kind]
    predicate = _text(modifier["applies_to"], f"{path}.applies_to")
    if predicate not in predicates:
        _fail(f"{path}.applies_to", f"incompatible with {kind}")
    number = modifier["value"]
    if rule == "true":
        valid = number is True
    elif type(number) not in (int, float) or not math.isfinite(number):
        valid = False
    elif rule == "positive_fraction_at_most_one":
        valid = 0 < number <= 1
    else:
        valid = (
            number % 1 == 0
            and {
                "positive_integer": number > 0,
                "negative_integer": number < 0,
                "nonnegative_integer": number >= 0,
                "integer_at_least_two": number >= 2,
            }[rule]
        )
    if not valid:
        _fail(f"{path}.value", f"expected {rule}")


def _readiness(fields: dict, path: str) -> None:
    if fields["status"] not in {"active", "pending"}:
        _fail(f"{path}.status", "unknown status")
    _engine_resolution(fields, path)


def _engine_resolution(fields: dict, path: str) -> None:
    if "resolution" in fields and _text(fields["resolution"], f"{path}.resolution") not in {"narrated", "engine"}:
        _fail(f"{path}.resolution", "unknown resolution")
    if "implementation_id" in fields:
        _text(fields["implementation_id"], f"{path}.implementation_id")
    if (
        fields["status"] == "active"
        and fields.get("resolution") == "engine"
        and fields.get("implementation_id") not in engine_implementations()
    ):
        _fail(f"{path}.implementation_id", "active engine effect requires a registered implementation")


def _layer_1(value: object, path: str) -> None:
    gift = _object(value, path)
    for field in ("id", "name", "effect", "trigger", "recharge", "status"):
        if field not in gift:
            _fail(f"{path}.{field}", "required field")
        _text(gift[field], f"{path}.{field}")
    if gift["status"] not in {"active", "narrated", "awaits_healing"}:
        _fail(f"{path}.status", "unknown status")
    if gift["recharge"] not in {"always", "per_encounter", "short_rest", "long_rest"}:
        _fail(f"{path}.recharge", "unknown recharge")
    _engine_resolution(gift, path)


def _matrix(value: object, path: str) -> None:
    matrix = _object(value, path)
    if matrix.keys() != archetype_ids():
        _fail(
            path,
            "expected exact archetype roster; missing="
            + str(sorted(archetype_ids() - matrix.keys()))
            + "; unknown="
            + str(sorted(matrix.keys() - archetype_ids())),
        )
    for archetype, entry in matrix.items():
        row_path = f"{path}.{archetype}"
        row = _object(entry, row_path, {"type", "name", "clauses"})
        if row["type"] not in ("natural", "divine", "unexpected"):
            _fail(f"{row_path}.type", "unknown synergy type")
        _text(row["name"], f"{row_path}.name")
        if not isinstance(row["clauses"], list) or not row["clauses"]:
            _fail(f"{row_path}.clauses", "expected nonempty array")
        for i, entry in enumerate(row["clauses"]):
            clause_path = f"{row_path}.clauses[{i}]"
            clause = _object(entry, clause_path)
            _object(clause, clause_path, {"effect", "status", "resolution"} | ({"implementation_id"} & clause.keys()))
            _text(clause["effect"], f"{clause_path}.effect")
            _text(clause["status"], f"{clause_path}.status")
            _text(clause["resolution"], f"{clause_path}.resolution")
            _readiness(clause, clause_path)


def _validate_gods(entries: object) -> list[dict]:
    archetype_ids()
    engine_implementations()
    if not isinstance(entries, list) or not entries:
        raise ValueError("gods: expected nonempty array")
    patrons: set[str] = set()
    ability_ids: set[str] = set()
    for index, entry in enumerate(entries):
        row = _object(entry, f"gods[{index}].god_id")
        patron = _text(row.get("god_id"), f"gods[{index}].god_id")
        if patron in patrons:
            _fail(f"{patron}.god_id", "duplicate patron")
        patrons.add(patron)
        _layer_1(row.get("layer_1_gift"), f"{patron}.layer_1_gift")
        path = f"{patron}.layer_2_resonance"
        layer = _object(row.get("layer_2_resonance"), path, {"name", "effect", "modifiers"})
        for field in ("name", "effect"):
            _text(layer[field], f"{path}.{field}")
        modifiers = layer["modifiers"]
        if not isinstance(modifiers, list) or not modifiers:
            _fail(f"{path}.modifiers", "expected nonempty array")
        for i, modifier in enumerate(modifiers):
            _modifier(modifier, f"{path}.modifiers[{i}]")
        path = f"{patron}.layer_3_tier_abilities"
        tiers = _object(row.get("layer_3_tier_abilities"), path, _TIERS)
        for tier, ability in tiers.items():
            ability_path = f"{path}.{tier}"
            fields = _object(
                ability,
                ability_path,
                {"id", "name", "effect", "recharge", "status", "resolution"}
                | ({"implementation_id"} & _object(ability, ability_path).keys()),
            )
            for field, value in fields.items():
                _text(value, f"{ability_path}.{field}")
            ability_id = fields["id"]
            if not re.fullmatch(re.escape(patron) + r"_[a-z0-9]+(?:_[a-z0-9]+)*", ability_id):
                _fail(f"{ability_path}.id", "expected patron-prefixed snake_case")
            if ability_id in ability_ids:
                _fail(f"{ability_path}.id", "duplicate ability id")
            ability_ids.add(ability_id)
            if fields["recharge"] not in {"always", "short_rest", "long_rest", "per_session"}:
                _fail(f"{ability_path}.recharge", "unknown recharge")
            _readiness(fields, ability_path)
        path = f"{patron}.layer_4_synergy_matrix"
        if "layer_4_synergy_matrix" not in row:
            _fail(path, "required field")
        _matrix(row["layer_4_synergy_matrix"], path)
    return entries


@functools.cache
def load_gods() -> list[dict]:
    """Return validated original dictionaries. Cached per process; do not mutate."""
    return _validate_gods(json.loads(_GODS_JSON_PATH.read_text()))
