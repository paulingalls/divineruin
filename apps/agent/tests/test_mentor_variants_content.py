"""Catalog conformance for content/mentor_variants.json (M9 / story-001).

Drives the production fail-loud parse_mentor_variant_row over the real catalog,
proving every entry conforms to the MentorVariant contract and cross-references a
real martial elective + an existing mentor NPC. Mirrors the TS conformance test
(apps/server/src/mentor_variants-load.test.ts); the unit-level parse/accessor
behavior lives in test_mentor_variants.py.
"""

import json
from collections import Counter, defaultdict
from pathlib import Path

from activity_templates import TRAINING_MENTORS
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


def test_variant_effect_contains_base_ability_effect():
    """Parity guard (concern dbc689 / retro Try): a variant's effect is its base ability's
    full effect text plus a cultural suffix (decision m9 override shape). If a base ability's
    effect is later edited, this catches the silent desync of its two variant rows — there is
    no other guard binding the duplicated copy to its source."""
    abilities = {a["id"]: a for a in _load("archetype_abilities.json")}
    for row in _variants():
        variant = parse_mentor_variant_row(row["id"], row)
        base = abilities[variant.ability_id]
        assert base["effect"] in variant.effect, (
            f"{variant.id}: base effect not contained in variant effect — stale copy after a base edit?"
        )


def test_each_culture_is_taught_by_exactly_one_mentor():
    """Concern 603af: the catalog must not alternate generic mentors across cultures. Each
    cultural martial style is taught by a single coherent mentor NPC (audio-first / dm-is-the-game)."""
    culture_mentors: dict[str, set[str]] = defaultdict(set)
    for row in _variants():
        variant = parse_mentor_variant_row(row["id"], row)
        culture_mentors[variant.cultural_attribution].add(variant.mentor_id)
    offenders = {c: sorted(ms) for c, ms in culture_mentors.items() if len(ms) != 1}
    assert not offenders, f"each culture must map to exactly one mentor, got {offenders}"


def test_every_mentor_id_resolves_in_training_mentors():
    """The narration prompt looks the variant's mentor up in TRAINING_MENTORS; an unknown id
    silently falls back to guildmaster_torin, breaking mentor-culture coherence in the DM voice
    (concern 603af). Every variant mentor must have a TRAINING_MENTORS persona."""
    for row in _variants():
        variant = parse_mentor_variant_row(row["id"], row)
        assert variant.mentor_id in TRAINING_MENTORS, (
            f"{variant.id} -> mentor {variant.mentor_id} missing from activity_templates.TRAINING_MENTORS"
        )


def test_narration_cues_vary_within_each_culture():
    """Concern 603af: narration_cue was one fixed string repeated 20x per culture, making the
    DM voice robotic when it narrates a variant. Each culture's variants must read distinctly."""
    culture_cues: dict[str, list[str]] = defaultdict(list)
    for row in _variants():
        variant = parse_mentor_variant_row(row["id"], row)
        culture_cues[variant.cultural_attribution].append(variant.narration_cue)
    offenders = {c: len(cues) for c, cues in culture_cues.items() if len(set(cues)) == 1}
    assert not offenders, f"these cultures have all-identical narration_cues (robotic): {offenders}"


def test_all_narration_cues_are_unique():
    """Stronger guard than per-culture variety: every variant gets its own cue, so no two
    learned variants ever make the DM voice the exact same line. Catches same-named techniques
    (e.g. warrior vs skirmisher 'Whirlwind') colliding under a shared cue template."""
    cues = [parse_mentor_variant_row(r["id"], r).narration_cue for r in _variants()]
    dupes = {c: n for c, n in Counter(cues).items() if n > 1}
    assert not dupes, f"narration_cues must be unique across the catalog; collisions: {dupes}"
