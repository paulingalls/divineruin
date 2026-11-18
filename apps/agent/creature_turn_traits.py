"""Catalog contracts for the Veilrender's deterministic turn effects."""

import re

from combat_damage_affinity import DAMAGE_TYPES


def validate_turn_traits(row):
    problems = []
    fields = {
        "corruption_field": {"save", "dc", "damage", "damage_type"},
        "regeneration": {"hp", "narration_cue", "suppressed_cue", "resumed_cue"},
    }
    if any(key in row for key in fields) and row.get("id") != "hollow_veilrender":
        problems.append("turn traits: require Veilrender catalog owner")
    for key, keys in fields.items():
        if key not in row:
            continue
        spec = row[key]
        if not isinstance(spec, dict) or set(spec) != keys:
            problems.append(f"{key}: expected exact fields {sorted(keys)}")
            continue
        for name, value in spec.items():
            valid = (
                type(value) is int and value > 0
                if name in ("hp", "dc")
                else value in ("STR", "DEX", "CON", "INT", "WIS", "CHA")
                if name == "save"
                else isinstance(value, str) and re.fullmatch(r"[1-9][0-9]*d[1-9][0-9]*(?:[+-][0-9]+)?", value)
                if name == "damage"
                else value in DAMAGE_TYPES
                if name == "damage_type"
                else isinstance(value, str) and bool(value.strip())
            )
            if not valid:
                problems.append(f"{key}.{name}: invalid")
        if key == "corruption_field":
            hollow = row.get("hollow")
            if (
                not isinstance(hollow, dict)
                or type(hollow.get("corruption_aura")) is not int
                or hollow["corruption_aura"] <= 0
            ):
                problems.append("corruption_field: requires positive hollow.corruption_aura")
    return problems


def validate_snapshot(data):
    for p in data["participants"]:
        mechanics = ("corruption_field", "regeneration")
        if p.get("creature_id") == "hollow_veilrender" and any(p.get(k) is None for k in mechanics):
            raise ValueError("Veilrender mechanics missing: reset/reseed old snapshots")
        if p.get("creature_id") == "hollow_veilrender" and any(
            k not in p for k in ("radiant_suppression_pending", "regeneration_suppressed", "veilrender_turn_round")
        ):
            raise ValueError("Veilrender turn state missing: reset/reseed old snapshots")
        specs = {k: p[k] for k in mechanics if p.get(k) is not None}
        problems = validate_turn_traits({**specs, "id": p.get("creature_id"), "hollow": p.get("hollow")})
        receipt = p.get("veilrender_turn_round")
        if receipt is not None and (type(receipt) is not int or not 1 <= receipt <= data["round_number"]):
            problems.append("veilrender_turn_round: invalid")
        for key in ("radiant_suppression_pending", "regeneration_suppressed"):
            if type(p.get(key, False)) is not bool or (p.get(key) and not specs.get("regeneration")):
                problems.append(f"{key}: invalid")
        if specs and p.get("creature_id") != "hollow_veilrender":
            problems.append("Veilrender specs without catalog owner")
        if problems:
            raise ValueError("; ".join(problems))
