"""Shared fail-loud parse primitives for content loaders (loader-dedup chore).

Five DB/JSON content loaders (companion_profiles, role_archetypes, settlement_templates,
npcs, mentor_variants) turn a raw JSONB row into typed dataclasses, validating each field
at the boundary. The generic primitives — string, int, number, list, dict, attribute-block,
and optional variants — were copy-pasted across those five (and had begun to drift:
parse_number returned float in some, the raw value in others). They live here once now;
each loader imports what it needs and keeps only its domain-specific parsers (e.g.
_parse_attack, _parse_variant, _parse_cost).

These primitives take (raw, ctx). Note that spells.py uses a different (data, key, id)
idiom (_require_int) and is NOT a drop-in consumer; folding it in is a separate refactor,
not an import swap.

Every function takes the raw value plus a `ctx` string (the dotted field path, e.g.
"companion_kael.attacks[0].damage") used in the error message, raises ValueError on a type
mismatch, and never mutates its input — mirroring the TS loaders' typeof guards so a seeded
row rejects identically on both sides of the database.
"""

# The six character attributes, in canonical order. Shared by parse_attributes and by
# loader-side validations (e.g. a companion's save_proficiencies / scaling-step attribute).
ATTRIBUTE_KEYS = ("strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma")


def parse_str(raw: object, ctx: str) -> str:
    if not isinstance(raw, str):
        raise ValueError(f"{ctx} is not a string")
    return raw


def parse_int(raw: object, ctx: str) -> int:
    # bool is a subclass of int — exclude it explicitly, parity with the TS guard.
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise ValueError(f"{ctx} is not an int")
    return raw


def parse_number(raw: object, ctx: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{ctx} is not a number")
    return float(raw)


def parse_str_tuple(raw: object, ctx: str) -> tuple[str, ...]:
    if not isinstance(raw, list):
        raise ValueError(f"{ctx} is not a list")
    return tuple(parse_str(x, f"{ctx}[{i}]") for i, x in enumerate(raw))


def parse_str_list(raw: object, ctx: str) -> list[str]:
    if not isinstance(raw, list):
        raise ValueError(f"{ctx} is not a list")
    return [parse_str(x, f"{ctx}[{i}]") for i, x in enumerate(raw)]


def parse_dict(raw: object, ctx: str) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"{ctx} is not an object")
    return raw


def parse_int_dict(raw: object, ctx: str) -> dict[str, int]:
    """Validate an open-keyed str->int map (e.g. resonance/modifier tables), values included.

    Unlike parse_dict (a shallow object guard) this deep-validates each value as an int,
    so a stringly-typed value fails loud at the boundary instead of slipping through to a
    cast-time TypeError. Keys are open (caller-defined ids), so only values are checked.
    """
    if not isinstance(raw, dict):
        raise ValueError(f"{ctx} is not an object")
    return {k: parse_int(v, f"{ctx}[{k}]") for k, v in raw.items()}


def parse_attributes(raw: object, ctx: str) -> dict[str, int]:
    if not isinstance(raw, dict):
        raise ValueError(f"{ctx} is not an object")
    return {k: parse_int(raw[k], f"{ctx}.{k}") for k in ATTRIBUTE_KEYS}


def opt_str(raw: object, ctx: str) -> str | None:
    return None if raw is None else parse_str(raw, ctx)


def opt_int(raw: object, ctx: str) -> int | None:
    return None if raw is None else parse_int(raw, ctx)
