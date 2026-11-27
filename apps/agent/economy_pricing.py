"""Validate the economy row for both runtime reads and transactional reseeds."""

import math

from catalog_parse import parse_dict
from sale_pricing import MERCHANT_KINDS, SALE_DISPOSITIONS, SETTLEMENT_PERSONALITIES
from workspace import SettlementSize

MAX_DISPOSITION_MULTIPLIER = 1e304
DISPOSITION_MULTIPLIER_CAP_RULE = f"must be <= {MAX_DISPOSITION_MULTIPLIER}"


def _as_json_number(value: int | float) -> float:
    """The value as the TS parser sees it: JSON.parse collapses a literal outside
    float range to Infinity, while Python keeps an unbounded int and then raises a
    bare OverflowError on the first float op. Mirror JS so both refuse the same row
    with the same rule (constraint 7).
    """
    try:
        return float(value)
    except OverflowError:
        return math.inf


def _validate_multiplier(raw: object, ctx: str, *, positive: bool = False) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{ctx} must be a number")
    value = _as_json_number(raw)
    if not math.isfinite(value):
        raise ValueError(f"{ctx} must be finite")
    if value < 0:
        raise ValueError(f"{ctx} must be >= 0")
    if positive and value == 0:
        raise ValueError(f"{ctx} must be > 0")
    if value > MAX_DISPOSITION_MULTIPLIER:
        raise ValueError(f"{ctx} {DISPOSITION_MULTIPLIER_CAP_RULE}")
    scaled = value * 10_000
    if (positive and scaled < 0.5) or abs(scaled - round(scaled)) >= 1e-9:
        raise ValueError(f"{ctx} must have at most 4 decimal places")
    return value


def _require_fields(raw: object, fields: tuple[str, ...], ctx: str) -> dict:
    data = parse_dict(raw, ctx)
    if data.keys() != set(fields):
        raise ValueError(f"{ctx} requires exactly {', '.join(fields)}")
    return data


def _validate_merchant_pricing(data: dict) -> None:
    ctx = "pricing[economy].merchant_gold_sp"
    matrix = _require_fields(data.get("merchant_gold_sp"), tuple(SettlementSize), ctx)
    for tier, row in matrix.items():
        for kind, value in _require_fields(row, MERCHANT_KINDS, f"{ctx}.{tier}").items():
            if value is not None and (type(value) not in (int, float) or not 0 <= value <= 2**53 - 1 or value % 1 != 0):
                raise ValueError(f"{ctx}.{tier}.{kind} must be a non-negative safe integer or null")

    ctx = "pricing[economy].merchant_gold_personality_multipliers"
    traits = _require_fields(data.get("merchant_gold_personality_multipliers"), SETTLEMENT_PERSONALITIES, ctx)
    for trait, value in traits.items():
        field = f"{ctx}.{trait}"
        if trait == "military":
            for kind, multiplier in _require_fields(value, ("arms", "other"), field).items():
                _validate_multiplier(multiplier, f"{field}.{kind}", positive=True)
        else:
            _validate_multiplier(value, field, positive=True)


def parse_economy_pricing(data: dict) -> dict:
    for key, value in data["disposition_multipliers"].items():
        _validate_multiplier(value, f"pricing[economy].disposition_multipliers.{key}")

    for key, value in data["repair_cost_sp"].items():
        ctx = f"pricing[economy].repair_cost_sp.{key}"
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{ctx} must be an integer")
        if not math.isfinite(_as_json_number(value)):
            raise ValueError(f"{ctx} must be an integer")
        if value < 0:
            raise ValueError(f"{ctx} must be >= 0")
    _validate_multiplier(data.get("silver_per_gold"), "pricing[economy].silver_per_gold", positive=True)
    sale_rate = _validate_multiplier(data.get("sale_rate"), "pricing[economy].sale_rate", positive=True)
    _validate_multiplier(data.get("crafted_sale_rate"), "pricing[economy].crafted_sale_rate", positive=True)
    multipliers = parse_dict(data.get("sale_disposition_multipliers"), "pricing[economy].sale_disposition_multipliers")
    for disposition in SALE_DISPOSITIONS:
        ctx = f"pricing[economy].sale_disposition_multipliers.{disposition}"
        multiplier = _validate_multiplier(multipliers.get(disposition), ctx, positive=True)
        # Keep the composed rate on a whole basis point for both rounding implementations.
        _validate_multiplier(sale_rate * multiplier, f"{ctx} * sale_rate", positive=True)
    _validate_merchant_pricing(data)
    return data
