import json
from pathlib import Path

import pytest

import combat_ability_save
import conditions

REPO_ROOT = Path(__file__).resolve().parents[4]
ABILITIES_PATH = REPO_ROOT / "content" / "archetype_abilities.json"
SPELLS_PATH = REPO_ROOT / "content" / "spells.json"
NO_SAVE_BUFF_CONDITIONS = frozenset({"inspired"})
SPELL_BUFF_CONDITIONS = combat_ability_save.BENEFICIAL_CONDITIONS


def _assert_no_hostile_condition_ability_omits_its_save(rows: list[dict[str, object]]) -> None:
    # A renamed key or a re-shaped file leaves the walk inspecting nothing and green forever,
    # so an empty walk reds rather than certifying.
    condition_rows = [row for row in rows if isinstance(row, dict) and "applies_condition" in row]
    assert condition_rows, rows
    violations = {
        row["id"]: row["applies_condition"]
        for row in condition_rows
        if "save" not in row and row["applies_condition"] not in NO_SAVE_BUFF_CONDITIONS
    }
    assert not violations, violations


def _assert_exempt_conditions_are_catalog_buffs(exempt: frozenset[str]) -> None:
    # The exemption is this guard's own escape hatch: a one-word edit would otherwise silence it
    # for a hostile condition. Only a catalog bonus-die buff may sit in the set.
    not_buffs = {condition for condition in exempt if not conditions.CONDITION_CATALOG[condition].bonus_die}
    assert not not_buffs, not_buffs


def _assert_no_hostile_condition_spell(rows: list[dict[str, object]]) -> None:
    condition_rows = [row for row in rows if isinstance(row, dict) and "applies_condition" in row]
    assert condition_rows, rows
    violations = {
        row["id"]: row["applies_condition"]
        for row in condition_rows
        if row["applies_condition"] not in SPELL_BUFF_CONDITIONS
    }
    assert not violations, violations


def test_no_hostile_condition_ability_omits_its_save():
    _assert_no_hostile_condition_ability_omits_its_save(json.loads(ABILITIES_PATH.read_text()))


def test_no_hostile_condition_spell_bypasses_the_target_gate():
    _assert_no_hostile_condition_spell(json.loads(SPELLS_PATH.read_text()))


def test_scratch_hostile_condition_spell_names_row():
    rows: list[dict[str, object]] = [{"id": "scratch_charm", "applies_condition": "charmed"}]
    with pytest.raises(AssertionError, match="scratch_charm"):
        _assert_no_hostile_condition_spell(rows)


def test_scratch_spell_walk_that_inspects_nothing_reds():
    with pytest.raises(AssertionError):
        _assert_no_hostile_condition_spell([])


def test_exempt_conditions_are_catalog_buffs():
    _assert_exempt_conditions_are_catalog_buffs(NO_SAVE_BUFF_CONDITIONS)


def test_scratch_hostile_no_save_ability_names_row():
    rows: list[dict[str, object]] = [{"id": "scratch_charm", "applies_condition": "charmed"}]

    with pytest.raises(AssertionError, match="scratch_charm"):
        _assert_no_hostile_condition_ability_omits_its_save(rows)


def test_scratch_walk_that_inspects_nothing_reds():
    with pytest.raises(AssertionError):
        _assert_no_hostile_condition_ability_omits_its_save([])


def test_scratch_hostile_condition_cannot_hide_in_the_exemption():
    with pytest.raises(AssertionError, match="charmed"):
        _assert_exempt_conditions_are_catalog_buffs(frozenset({"inspired", "charmed"}))


def test_spell_exemptions_are_exactly_the_runtime_beneficial_conditions():
    assert {"blessed", "shielded", "enraged", "inspired"} == SPELL_BUFF_CONDITIONS
