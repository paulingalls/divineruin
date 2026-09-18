import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
ABILITIES_PATH = REPO_ROOT / "content" / "archetype_abilities.json"
NO_SAVE_BUFF_CONDITIONS = frozenset({"inspired"})


def _assert_no_hostile_condition_ability_omits_its_save(rows: list[dict[str, object]]) -> None:
    violations = {
        row["id"]: row["applies_condition"]
        for row in rows
        if "applies_condition" in row and "save" not in row and row["applies_condition"] not in NO_SAVE_BUFF_CONDITIONS
    }
    assert not violations, violations


def test_no_hostile_condition_ability_omits_its_save():
    _assert_no_hostile_condition_ability_omits_its_save(json.loads(ABILITIES_PATH.read_text()))


def test_scratch_hostile_no_save_ability_names_row():
    rows: list[dict[str, object]] = [{"id": "scratch_charm", "applies_condition": "charmed"}]

    with pytest.raises(AssertionError, match="scratch_charm"):
        _assert_no_hostile_condition_ability_omits_its_save(rows)
