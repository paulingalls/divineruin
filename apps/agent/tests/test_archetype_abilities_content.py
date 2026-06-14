"""Content tests for content/archetype_abilities.json — the M2.2 ability SSOT.

These read the raw JSON file directly (NOT a loader; the loader lives in
apps/agent/abilities.py, story-002). This module checks the JSON's structure:
roster coverage (every archetype has at least one core ability), the L4/L8
elective technique pool sizes, the closed ability_type vocabulary, the cost
object shape, and id well-formedness. Mirrors test_archetypes_content.py.

Scope (decision m22-core-spells-as-abilities): activatable abilities only —
core actives + casters' fixed core spells (ability_type=core), core reactions
(reaction), and L4/L8 elective techniques (elective). Passives, L5/L9
specialization-variant core spells, and elective spell progression are out of
M2.2.

Cost is a structured object (decision m22-cost-object-schema):
{stamina:int>=0, focus:int>=0, scaling:str|None}.
"""

import json
import re
from pathlib import Path

import pytest

ABILITIES_JSON = Path(__file__).resolve().parents[3] / "content" / "archetype_abilities.json"

# The 18 chassis ids (parity with content/archetypes.json roster).
ARCHETYPE_IDS = {
    "warrior",
    "guardian",
    "skirmisher",
    "mage",
    "artificer",
    "seeker",
    "druid",
    "beastcaller",
    "warden",
    "cleric",
    "paladin",
    "oracle",
    "rogue",
    "spy",
    "whisper",
    "bard",
    "diplomat",
    "marshal",
}

# Martial / support archetypes with elective technique pools at both L4 and L8.
POOLS_L4_AND_L8 = {"warrior", "guardian", "skirmisher", "rogue", "spy", "diplomat", "marshal"}
# Single-technique archetypes: one L4 pool only, no L8 technique pool.
POOLS_L4_ONLY = {"bard", "paladin"}

ABILITY_TYPES = {"core", "reaction", "elective"}

REQUIRED_KEYS = {
    "id",
    "archetype_id",
    "name",
    "ability_type",
    "level_requirement",
    "cost",
    "effect",
    "narration_cue",
}

# Spell-backed caster CORE rows (Arcane Bolt, Sacred Flame, …) drop their authored
# `cost` and carry a `spell_id` instead: the Focus cost — the one number shared with
# the cast path — composes from content/spells.json at load time (Try 2), so it can't
# drift. effect/level/narration stay authored per-archetype. So these rows REPLACE
# `cost` with `spell_id` and keep everything else.
SPELL_BACKED_KEYS = (REQUIRED_KEYS - {"cost"}) | {"spell_id"}

SPELLS_JSON = Path(__file__).resolve().parents[3] / "content" / "spells.json"

ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _is_spell_backed(row: dict) -> bool:
    return "spell_id" in row


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    data = json.loads(ABILITIES_JSON.read_text())
    assert isinstance(data, list), "archetype_abilities.json must be a top-level array"
    by_id = {row["id"]: row for row in data}
    assert len(by_id) == len(data), "duplicate ability id in archetype_abilities.json"
    return data


def _by_archetype(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {aid: [] for aid in ARCHETYPE_IDS}
    for row in rows:
        out.setdefault(row["archetype_id"], []).append(row)
    return out


def test_every_archetype_has_a_core_ability(rows):
    by_arch = _by_archetype(rows)
    for aid in ARCHETYPE_IDS:
        cores = [r for r in by_arch[aid] if r["ability_type"] == "core"]
        assert cores, f"{aid} has no core ability"


def test_elective_pool_sizes(rows):
    by_arch = _by_archetype(rows)
    for aid in POOLS_L4_AND_L8:
        l4 = [r for r in by_arch[aid] if r["ability_type"] == "elective" and r["level_requirement"] == 4]
        l8 = [r for r in by_arch[aid] if r["ability_type"] == "elective" and r["level_requirement"] == 8]
        assert len(l4) == 4, f"{aid} L4 elective pool has {len(l4)} options, expected 4"
        assert len(l8) == 4, f"{aid} L8 elective pool has {len(l8)} options, expected 4"
    for aid in POOLS_L4_ONLY:
        l4 = [r for r in by_arch[aid] if r["ability_type"] == "elective" and r["level_requirement"] == 4]
        l8 = [r for r in by_arch[aid] if r["ability_type"] == "elective" and r["level_requirement"] == 8]
        assert len(l4) == 4, f"{aid} L4 elective pool has {len(l4)} options, expected 4"
        assert len(l8) == 0, f"{aid} should have no L8 technique pool, found {len(l8)}"
    # The remaining archetypes (casters + whisper) have no elective technique
    # pools in M2.2 — a stray L4/L8 elective seeded on one must fail loudly.
    no_pool = ARCHETYPE_IDS - POOLS_L4_AND_L8 - POOLS_L4_ONLY
    for aid in no_pool:
        electives = [r for r in by_arch[aid] if r["ability_type"] == "elective"]
        assert not electives, (
            f"{aid} has no elective pool in M2.2 but found {len(electives)} elective row(s): "
            f"{[r['id'] for r in electives]}"
        )


def test_each_row_required_keys_and_enums(rows):
    for row in rows:
        rid = row.get("id", "<no id>")
        # Exact match, not superset: the row shape is the cross-language SSOT
        # contract for the story-002 (Python) and story-003 (TS) parsers, so a
        # stray/typo'd key must fail here rather than surface as a strict-parse
        # break downstream. A spell-backed CORE row REPLACES `cost` with `spell_id`
        # (the Focus cost composes from the catalog); everything else is identical.
        if _is_spell_backed(row):
            assert set(row) == SPELL_BACKED_KEYS, (
                f"{rid} spell-backed key mismatch: missing {SPELL_BACKED_KEYS - set(row)}, "
                f"extra {set(row) - SPELL_BACKED_KEYS}"
            )
            assert row["ability_type"] == "core", f"{rid} spell-backed rows must be ability_type=core"
            assert isinstance(row["spell_id"], str) and ID_RE.match(row["spell_id"]), (
                f"{rid} spell_id {row['spell_id']!r} must be a well-formed catalog spell id"
            )
        else:
            assert set(row) == REQUIRED_KEYS, (
                f"{rid} key mismatch: missing {REQUIRED_KEYS - set(row)}, extra {set(row) - REQUIRED_KEYS}"
            )
        # Common to both shapes — every row authors its own level/effect/name/narration.
        assert isinstance(row["level_requirement"], int) and row["level_requirement"] >= 1, (
            f"{rid} level_requirement must be a positive int"
        )
        assert isinstance(row["effect"], str) and row["effect"], f"{rid} effect must be a non-empty string"
        assert row["ability_type"] in ABILITY_TYPES, (
            f"{rid} ability_type {row['ability_type']!r} not in {sorted(ABILITY_TYPES)}"
        )
        assert row["archetype_id"] in ARCHETYPE_IDS, (
            f"{rid} archetype_id {row['archetype_id']!r} is not a known chassis id"
        )
        assert isinstance(row["name"], str) and row["name"], f"{rid} name must be a non-empty string"
        assert isinstance(row["narration_cue"], str) and row["narration_cue"], (
            f"{rid} narration_cue must be a non-empty string"
        )


def test_spell_backed_rows_reference_a_real_catalog_spell(rows):
    # Cross-file integrity: every spell_id must resolve in content/spells.json, or
    # the load-time composition fails loud at startup. Catches a typo'd spell_id.
    spells_raw = json.loads(SPELLS_JSON.read_text())

    def _spell_ids(obj):
        if isinstance(obj, dict):
            if "spell_tier" in obj and "focus_cost" in obj:
                yield obj["id"]
            else:
                for v in obj.values():
                    yield from _spell_ids(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from _spell_ids(v)

    catalog_ids = set(_spell_ids(spells_raw))
    for row in rows:
        if _is_spell_backed(row):
            assert row["spell_id"] in catalog_ids, (
                f"{row['id']} references spell_id {row['spell_id']!r} not in content/spells.json"
            )


def test_cost_shape(rows):
    for row in rows:
        rid = row.get("id", "<no id>")
        if _is_spell_backed(row):
            continue  # cost is composed from the catalog, not authored on the row
        cost = row["cost"]
        assert isinstance(cost, dict), f"{rid} cost must be an object"
        assert set(cost) == {"stamina", "focus", "scaling"}, (
            f"{rid} cost keys {sorted(cost)} != ['focus', 'scaling', 'stamina']"
        )
        # bool is a subclass of int — exclude it explicitly.
        assert isinstance(cost["stamina"], int) and not isinstance(cost["stamina"], bool) and cost["stamina"] >= 0, (
            f"{rid} cost.stamina must be an int >= 0"
        )
        assert isinstance(cost["focus"], int) and not isinstance(cost["focus"], bool) and cost["focus"] >= 0, (
            f"{rid} cost.focus must be an int >= 0"
        )
        assert cost["scaling"] is None or isinstance(cost["scaling"], str), (
            f"{rid} cost.scaling must be a string or null"
        )


def test_ids_unique_and_well_formed(rows):
    for row in rows:
        rid = row["id"]
        assert isinstance(rid, str) and ID_RE.match(rid), f"malformed ability id: {rid!r}"
