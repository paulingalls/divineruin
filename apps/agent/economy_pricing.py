"""Validate the economy row for both runtime reads and transactional reseeds."""

import math

from catalog_parse import parse_dict
from inventory_pools import MERCHANT_KINDS
from role_archetypes import DISPOSITIONS
from sale_pricing import ECONOMY_SIZES, ECONOMY_TRAITS, SALE_DISPOSITIONS

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
    matrix = _require_fields(data.get("merchant_gold_sp"), ECONOMY_SIZES, ctx)
    for tier, row in matrix.items():
        for kind, value in _require_fields(row, MERCHANT_KINDS, f"{ctx}.{tier}").items():
            if value is not None and (type(value) not in (int, float) or not 0 <= value <= 2**53 - 1 or value % 1 != 0):
                raise ValueError(f"{ctx}.{tier}.{kind} must be a non-negative safe integer or null")

    ctx = "pricing[economy].merchant_gold_personality_multipliers"
    traits = _require_fields(data.get("merchant_gold_personality_multipliers"), ECONOMY_TRAITS, ctx)
    for trait, value in traits.items():
        field = f"{ctx}.{trait}"
        if trait == "military":
            for kind, multiplier in _require_fields(value, ("arms", "other"), field).items():
                _validate_multiplier(multiplier, f"{field}.{kind}", positive=True)
        else:
            _validate_multiplier(value, field, positive=True)


def _validate_stock_modifiers(raw: object) -> None:
    ctx = "pricing[economy].stock_modifiers"
    traits = _require_fields(raw, ECONOMY_TRAITS, ctx)
    for trait, value in traits.items():
        field = f"{ctx}.{trait}"
        row = _require_fields(value, ("quantity_multiplier", "tier_3_allowed", "tier_3_chance_bonus"), field)
        quantity = row["quantity_multiplier"]
        quantity_ctx = f"{field}.quantity_multiplier"
        if trait == "military":
            quantities = parse_dict(quantity, quantity_ctx)
            if not quantities:
                raise ValueError(f"{quantity_ctx} requires at least one pool")
            for pool, multiplier in quantities.items():
                _validate_multiplier(multiplier, f"{quantity_ctx}.{pool}", positive=True)
        else:
            _validate_multiplier(quantity, quantity_ctx, positive=True)
        if not isinstance(row["tier_3_allowed"], bool):
            raise ValueError(f"{field}.tier_3_allowed must be a boolean")
        chance_ctx = f"{field}.tier_3_chance_bonus"
        if _validate_multiplier(row["tier_3_chance_bonus"], chance_ctx) > 1:
            raise ValueError(f"{chance_ctx} must be <= 1")


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
    ctx = "pricing[economy].purchase_disposition_multipliers"
    purchase_rates = _require_fields(data.get("purchase_disposition_multipliers"), DISPOSITIONS, ctx)
    for disposition, multiplier in purchase_rates.items():
        _validate_multiplier(multiplier, f"{ctx}.{disposition}", positive=True)
    _validate_multiplier(
        data.get("purchase_frontier_multiplier"), "pricing[economy].purchase_frontier_multiplier", positive=True
    )
    _validate_merchant_pricing(data)
    _validate_stock_modifiers(data.get("stock_modifiers"))
    return data
