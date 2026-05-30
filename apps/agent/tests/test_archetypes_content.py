"""Content tests for content/archetypes.json — the M2.1 chassis SSOT.

These read the raw JSON file (NOT a loader; the loader is story-002) and prove
the fold from the scattered code constants is LOSSLESS: every archetype's HP,
resource pattern/formulas, save proficiencies, and starting-skill pool must
match the legacy ARCHETYPE_HP_CONFIG (hp_scaling), ARCHETYPE_RESOURCE_CONFIG
(rules_engine), and CLASSES (creation_classes) exactly. Armor/weapon
proficiency lists are NEW (no legacy source) — checked only for non-emptiness.
"""

import json
from pathlib import Path

import pytest

from creation_classes import CLASSES
from hp_scaling import ARCHETYPE_HP_CONFIG
from rules_engine import ARCHETYPE_RESOURCE_CONFIG, PoolFormula

ARCHETYPES_JSON = Path(__file__).resolve().parents[3] / "content" / "archetypes.json"

EXPECTED_IDS = {
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

REQUIRED_KEYS = {
    "id",
    "hp",
    "resource",
    "save_proficiencies",
    "armor_proficiencies",
    "weapon_proficiencies",
    "starting_skills",
}


def _serialize_formula(formula: PoolFormula | None) -> dict | None:
    if formula is None:
        return None
    return {
        "base": formula.base,
        "attribute": formula.attribute,
        "level_divisor": formula.level_divisor,
    }


@pytest.fixture(scope="module")
def archetypes() -> dict[str, dict]:
    rows = json.loads(ARCHETYPES_JSON.read_text())
    assert isinstance(rows, list), "archetypes.json must be a top-level array"
    by_id = {row["id"]: row for row in rows}
    assert len(by_id) == len(rows), "duplicate archetype id in archetypes.json"
    return by_id


def test_all_18_archetypes_present(archetypes):
    assert set(archetypes) == EXPECTED_IDS
    # The four sources must agree on the archetype roster (no drift).
    assert set(archetypes) == set(ARCHETYPE_HP_CONFIG) == set(ARCHETYPE_RESOURCE_CONFIG) == set(CLASSES)


def test_each_row_has_required_keys(archetypes):
    for aid, row in archetypes.items():
        assert set(row) >= REQUIRED_KEYS, f"{aid} missing keys: {REQUIRED_KEYS - set(row)}"
        assert row["id"] == aid


def test_hp_parity_with_legacy_config(archetypes):
    for aid, row in archetypes.items():
        cfg = ARCHETYPE_HP_CONFIG[aid]
        assert row["hp"] == {
            "base": cfg.base,
            "growth": cfg.growth,
            "category": cfg.category,
        }, f"{aid} hp diverges from ARCHETYPE_HP_CONFIG"


def test_resource_parity_with_legacy_config(archetypes):
    for aid, row in archetypes.items():
        pattern, stamina_formula, focus_formula = ARCHETYPE_RESOURCE_CONFIG[aid]
        assert row["resource"] == {
            "pattern": pattern,
            "stamina_formula": _serialize_formula(stamina_formula),
            "focus_formula": _serialize_formula(focus_formula),
        }, f"{aid} resource diverges from ARCHETYPE_RESOURCE_CONFIG"


def test_saves_and_skills_parity_with_classes(archetypes):
    for aid, row in archetypes.items():
        cls = CLASSES[aid]
        assert row["save_proficiencies"] == list(cls.saving_throw_proficiencies), (
            f"{aid} save_proficiencies diverge from CLASSES"
        )
        assert row["starting_skills"] == {
            "options": list(cls.skill_options),
            "num_choices": cls.num_skill_choices,
        }, f"{aid} starting_skills diverge from CLASSES"


def test_armor_and_weapon_proficiencies_nonempty(archetypes):
    for aid, row in archetypes.items():
        armor = row["armor_proficiencies"]
        weapons = row["weapon_proficiencies"]
        assert isinstance(armor, list) and armor and all(isinstance(t, str) for t in armor), (
            f"{aid} armor_proficiencies must be a non-empty list of strings"
        )
        assert isinstance(weapons, list) and weapons and all(isinstance(t, str) for t in weapons), (
            f"{aid} weapon_proficiencies must be a non-empty list of strings"
        )
