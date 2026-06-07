"""Catalog conformance for content/mentor_variants.json (M9 / story-001).

Drives the production fail-loud parse_mentor_variant_row over the real catalog,
proving every entry conforms to the MentorVariant contract and cross-references a
real martial elective + an existing mentor NPC. Mirrors the TS conformance test
(apps/server/src/mentor_variants-load.test.ts); the unit-level parse/accessor
behavior lives in test_mentor_variants.py.
"""

import json
from collections import Counter
from pathlib import Path

from mentor_variants import parse_mentor_variant_row

_ROOT = Path(__file__).resolve().parents[3]
_CONTENT = _ROOT / "content"

# Closed set (story-001): 40 martial elective techniques x 2 cultural variants.
_VARIANT_COUNT = 80
_MARTIAL_ARCHETYPES = {"warrior", "guardian", "skirmisher", "rogue", "spy"}


def _load(name: str) -> list[dict]:
    return json.loads((_CONTENT / name).read_text())


def _variants() -> list[dict]:
    return _load("mentor_variants.json")


def test_exactly_80_entries_each_parses():
    rows = _variants()
    assert len(rows) == _VARIANT_COUNT
    for row in rows:
        parse_mentor_variant_row(row["id"], row)  # raises on any malformed row


def test_ids_are_unique():
    # Seed upserts by id, so a duplicate id silently seeds <80 distinct DB rows
    # while the count and 2-per-technique checks still pass. Pin uniqueness here.
    ids = [row["id"] for row in _variants()]
    dupes = {i: n for i, n in Counter(ids).items() if n > 1}
    assert not dupes, f"duplicate variant ids would seed <{_VARIANT_COUNT} distinct rows: {dupes}"


def test_every_ability_id_is_a_real_martial_elective():
    abilities = _load("archetype_abilities.json")
    martial_electives = {
        a["id"] for a in abilities if a["archetype_id"] in _MARTIAL_ARCHETYPES and a["ability_type"] == "elective"
    }
    for row in _variants():
        variant = parse_mentor_variant_row(row["id"], row)
        assert variant.ability_id in martial_electives, f"{variant.id} -> unknown elective {variant.ability_id}"


def test_every_mentor_id_is_an_existing_npc():
    npc_ids = {n["id"] for n in _load("npcs.json")}
    for row in _variants():
        variant = parse_mentor_variant_row(row["id"], row)
        assert variant.mentor_id in npc_ids, f"{variant.id} -> unknown mentor {variant.mentor_id}"


def test_every_martial_elective_has_exactly_two_variants():
    counts = Counter(parse_mentor_variant_row(r["id"], r).ability_id for r in _variants())
    assert len(counts) == 40
    offenders = {ability: n for ability, n in counts.items() if n != 2}
    assert not offenders, f"expected 2 variants per technique, got {offenders}"
