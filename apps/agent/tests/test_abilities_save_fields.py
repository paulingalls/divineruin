import pytest

import abilities


def _row(**overrides):
    row = {
        "archetype_id": "warrior",
        "name": "Test Charge",
        "ability_type": "elective",
        "level_requirement": 8,
        "cost": {"stamina": 4, "focus": 0, "scaling": None},
        "effect": "Knock a foe prone.",
        "narration_cue": "A hard charge.",
        "applies_condition": "prone",
        "save": "strength",
        "dc_attribute": "strength",
    }
    row.update(overrides)
    return row


def test_save_fields_reach_the_parsed_ability():
    ability = abilities.parse_ability_row("test_charge", _row())

    assert ability.save == "strength"
    assert ability.dc_attribute == "strength"


def test_real_charge_has_paired_save_fields():
    ability = abilities.get_ability("warrior_unstoppable_charge")

    assert ability.applies_condition == "prone"
    assert ability.save == "strength"
    assert ability.dc_attribute == "strength"


@pytest.mark.parametrize(
    ("row", "field"),
    [
        (_row(dc_attribute=None), "dc_attribute"),
        (_row(save=None), "save"),
        (_row(applies_condition=None), "applies_condition"),
        (_row(save="might"), "save"),
        (_row(dc_attribute="might"), "dc_attribute"),
    ],
)
def test_malformed_save_fields_fail_loud(row, field):
    row = {key: value for key, value in row.items() if value is not None}

    with pytest.raises(ValueError, match=rf"test_charge.*{field}"):
        abilities.parse_ability_row("test_charge", row)
