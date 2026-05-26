"""Quality-outcome tables + the pure band-keyed selector (M5.3 crafting).

quality_outcomes is DB-loaded content (content/quality_outcomes.json, decision
quality-outcomes-storage): per-category bonus-property and flaw tables, one row
per crafting category. Read only by the Python rules engine — no TS consumer
resolves quality, so (unlike recipes) there is no TS accessor. Mirrors recipes.py:
a fail-loud parse_quality_outcome_row plus a cached get_quality_outcomes accessor
keyed quality_outcome:<category>.

apply_quality_outcome is the pure selector story-003's resolve_crafting calls once
the band is known (decision apply-quality-outcome-signature): it takes the already
derived band — never the roll margin — so the DC+10/-5 thresholds live in exactly
one place (the resolver). Exceptional draws a bonus_property, Partial draws a flaw,
Success/Failure draw nothing. Entries are narration-only {id,name,description}
(decision bonus-property-shape); mechanical effects wait for M5.4 item plumbing.
"""

import json
import logging
import random

import db

logger = logging.getLogger("divineruin.quality_outcomes")

# The crafting categories, matching recipes.py _CATEGORIES / recipe.ts. A content
# row keyed by anything else fails loud at the load boundary.
_CATEGORIES = {"weapon", "armor", "consumable", "tool", "enchantment", "ammunition"}

# Bands that draw from a table. Success/Failure draw nothing; an unknown band is a
# caller bug (the resolver only ever passes a canonical band) and fails loud.
_BONUS_BAND = "exceptional"
_FLAW_BAND = "partial"
_NO_DRAW_BANDS = {"success", "failure"}


def _parse_entry(raw: object, ctx: str) -> dict:
    """Validate one narration-only {id,name,description} entry in isolation."""
    if not isinstance(raw, dict):
        raise ValueError(f"{ctx} is not an object")
    out = {}
    for field in ("id", "name", "description"):
        value = raw.get(field)
        if not isinstance(value, str) or len(value) == 0:
            raise ValueError(f"{ctx}.{field} is not a non-empty string")
        out[field] = value
    return out


def _parse_entry_list(raw: object, ctx: str) -> list[dict]:
    if not isinstance(raw, list):
        raise ValueError(f"{ctx} is not an array")
    if len(raw) == 0:
        raise ValueError(f"{ctx} is empty")
    return [_parse_entry(e, f"{ctx}[{i}]") for i, e in enumerate(raw)]


def parse_quality_outcome_row(category_id: str, raw: object) -> dict:
    """Fail-loud parser for one quality_outcomes-table row's `data` payload.

    Mirrors recipes.parse_recipe_row: id (the crafting category) comes from the row
    key, not the data; raises ValueError with a quality_outcomes[<id>].<field>
    context on any mismatch. Validates the category against _CATEGORIES and both
    bonus_properties + flaws as non-empty lists of {id,name,description} entries.
    """
    ctx = f"quality_outcomes[{category_id}]"
    if category_id not in _CATEGORIES:
        raise ValueError(f"{ctx} is not a known crafting category")
    if not isinstance(raw, dict):
        raise ValueError(f"{ctx}.data is not an object")

    bonus_properties = _parse_entry_list(raw.get("bonus_properties"), f"{ctx}.bonus_properties")
    flaws = _parse_entry_list(raw.get("flaws"), f"{ctx}.flaws")

    return {
        "id": category_id,
        "bonus_properties": bonus_properties,
        "flaws": flaws,
    }


def apply_quality_outcome(band: str, category_tables: dict, *, rng: random.Random) -> dict | None:
    """Select the quality property for a resolved crafting band.

    Pure: takes the already-derived band (not the roll margin — the resolver owns
    the thresholds) and the parsed category tables, draws deterministically from
    `rng`. Exceptional -> a bonus_property; Partial -> a flaw; Success/Failure ->
    None. An unknown band is a caller bug and fails loud.
    """
    if band == _BONUS_BAND:
        return rng.choice(category_tables["bonus_properties"])
    if band == _FLAW_BAND:
        return rng.choice(category_tables["flaws"])
    if band in _NO_DRAW_BANDS:
        return None
    raise ValueError(f"apply_quality_outcome got unexpected band {band!r}")


async def get_quality_outcomes(category: str) -> dict | None:
    """Return the parsed bonus/flaw tables for a crafting category, or None.

    Caches the PARSED dict (parse-once) under quality_outcome:<category>, mirroring
    get_recipe. Round-trips cleanly through json (parser emits only str/list/dict).
    """
    cache_key = f"quality_outcome:{category}"
    cached = await db._cache_get(cache_key)
    if cached is not None:
        return json.loads(cached)

    pool = await db.get_pool()
    row = await pool.fetchrow("SELECT data FROM quality_outcomes WHERE id = $1", category)
    if row is None:
        return None

    parsed = parse_quality_outcome_row(category, json.loads(row["data"]))
    await db._cache_set(cache_key, json.dumps(parsed))
    return parsed
