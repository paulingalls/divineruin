"""Settlement templates — DB-loaded content catalog (Phase 6 / M6.2, story-002).

content/settlement_templates.json is the single source of truth for settlement
population templates. This module is the in-memory catalog that settlement NPC
generation reads synchronously, mirroring role_archetypes.py / npcs.py: module-global
dicts populated by load_settlement_templates() at startup (or set_settlement_templates()
in tests), a fail-loud parse_settlement_template_row shared by the DB loader and the
JSON test fixture, and sync accessors.

The catalog is a flat list of self-contained id/JSONB rows discriminated by `kind`:
  - tier rows (kind="tier", id == SettlementSize): role_counts mapping role_archetype
    ids to {min, max} integer ranges.
  - personality rows (kind="personality", id == trait): role_frequency_modifiers and
    disposition_modifiers (role_archetype id -> int), price_modifier, inventory_modifier,
    description.

story-003 (generate_settlement_npcs / instantiate_npc_from_template) consumes this:
get_settlement_tier(size) for role counts, get_settlement_personality(trait) for
modifiers. Role-id validity (role_counts / modifier keys reference real archetypes) is a
cross-file invariant guarded by the conformance test, not the loader — keeping the loader
self-contained (no load-order coupling to role_archetypes), mirroring how location-exit
refs are validated in content tests rather than the location loader.
"""

import json
import logging

logger = logging.getLogger("divineruin.settlement_templates")

_tiers: dict[str, dict] = {}
_personalities: dict[str, dict] = {}


def _parse_str(raw: object, ctx: str) -> str:
    if not isinstance(raw, str):
        raise ValueError(f"{ctx} is not a string")
    return raw


def _parse_int(raw: object, ctx: str) -> int:
    # bool is an int subclass; reject it — counts and deltas are real integers.
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise ValueError(f"{ctx} is not an int")
    return raw


def _parse_number(raw: object, ctx: str) -> float:
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        raise ValueError(f"{ctx} is not a number")
    return raw


def _parse_dict(raw: object, ctx: str) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"{ctx} is not an object")
    return raw


def _parse_tier(row_id: str, data: dict) -> None:
    role_counts = _parse_dict(data["role_counts"], f"{row_id}.role_counts")
    for role_id, rng in role_counts.items():
        ctx = f"{row_id}.role_counts[{role_id}]"
        rng = _parse_dict(rng, ctx)
        lo = _parse_int(rng["min"], f"{ctx}.min")
        hi = _parse_int(rng["max"], f"{ctx}.max")
        if lo < 0 or hi < lo:
            raise ValueError(f"{ctx} invalid range min={lo} max={hi}")


def _parse_personality(row_id: str, data: dict) -> None:
    for field in ("role_frequency_modifiers", "disposition_modifiers"):
        mods = _parse_dict(data[field], f"{row_id}.{field}")
        for role_id, delta in mods.items():
            _parse_int(delta, f"{row_id}.{field}[{role_id}]")
    _parse_number(data["price_modifier"], f"{row_id}.price_modifier")
    # inventory_modifier: prosperous>1.0 fuller, struggling<1.0 thinner; forward-wired
    # Phase-9 economy field (no live reader yet — debt recorded), story-003 scope expansion.
    _parse_number(data["inventory_modifier"], f"{row_id}.inventory_modifier")
    _parse_str(data["description"], f"{row_id}.description")


def parse_settlement_template_row(row_id: str, data: dict) -> dict:
    """Validate a raw settlement-template dict (JSON file or DB JSONB) fail-loud.

    Dispatches on `kind` ("tier" | "personality"), validates the kind-specific shape, and
    returns the row unchanged (consumers read it by key). Wraps the underlying error with
    the row id for context.
    """
    try:
        kind = _parse_str(data["kind"], f"{row_id}.kind")
        if kind == "tier":
            _parse_tier(row_id, data)
        elif kind == "personality":
            _parse_personality(row_id, data)
        else:
            raise ValueError(f"{row_id}.kind {kind!r} not in ('tier', 'personality')")
        return data
    except (KeyError, TypeError) as e:
        raise ValueError(f"Malformed settlement_templates row {row_id!r}: {e}") from e


def set_settlement_templates(tiers: dict[str, dict], personalities: dict[str, dict]) -> None:
    """Test seam: populate the catalog directly without going through the DB."""
    _tiers.clear()
    _tiers.update(tiers)
    _personalities.clear()
    _personalities.update(personalities)


def get_settlement_tier(size: str) -> dict:
    """Return the tier template for a SettlementSize, or raise if unknown."""
    try:
        return _tiers[size]
    except KeyError as e:
        raise ValueError(f"unknown settlement tier {size!r}") from e


def get_settlement_personality(trait: str) -> dict:
    """Return the personality template for a trait, or raise if unknown."""
    try:
        return _personalities[trait]
    except KeyError as e:
        raise ValueError(f"unknown settlement personality {trait!r}") from e


def is_loaded() -> bool:
    """True once both halves of the catalog have been populated (startup load or seam)."""
    return bool(_tiers) and bool(_personalities)


async def load_settlement_templates() -> None:
    """Load the settlement-template catalog from the DB into _tiers / _personalities.

    Called at agent startup beside load_role_archetypes(). Fails loud if the query or a
    row errors. Builds local dicts then swaps in one synchronous step (no await between),
    so a malformed row fails loud WITHOUT wiping an already-loaded catalog.
    """
    import db

    pool = await db.get_pool()
    rows = await pool.fetch("SELECT id, data FROM settlement_templates")
    tiers: dict[str, dict] = {}
    personalities: dict[str, dict] = {}
    for row in rows:
        data = json.loads(row["data"]) if isinstance(row["data"], str) else row["data"]
        parsed = parse_settlement_template_row(row["id"], data)
        (tiers if data["kind"] == "tier" else personalities)[row["id"]] = parsed
    _tiers.clear()
    _tiers.update(tiers)
    _personalities.clear()
    _personalities.update(personalities)
    logger.info("Loaded %d settlement tiers + %d personalities", len(_tiers), len(_personalities))
