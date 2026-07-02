"""Fail-loud unit coverage for the enemy applies_condition load-boundary guard (sprint-030
story-001). Encounter templates have no strict loader today (unlike spells.json /
archetype_abilities.json), so this guard is the only thing standing between a typo'd
applies_condition and a silent no-op at combat start. Pure — calls the validator directly
against an in-memory enemies list, no DB.
"""

import pytest

from combat_init import _validate_enemy_action_conditions


class TestValidateEnemyActionConditions:
    def test_unknown_condition_raises(self):
        enemies = [
            {
                "id": "bad_enemy",
                "action_pool": [
                    {"name": "Bad Howl", "applies_condition": "not_a_condition"},
                ],
            }
        ]
        with pytest.raises(ValueError, match="not_a_condition"):
            _validate_enemy_action_conditions(enemies)

    def test_known_hostile_condition_with_save_and_dc_does_not_raise(self):
        enemies = [
            {
                "id": "hollow_rend_1",
                "action_pool": [
                    {"name": "Hollow Shriek", "applies_condition": "frightened", "save": "wisdom", "dc": 12},
                ],
            }
        ]
        _validate_enemy_action_conditions(enemies)  # no raise

    def test_missing_save_raises_at_load(self):
        # The resolver hard-reads action["save"]; a missing save must fail loud HERE (combat start),
        # not as a mid-fight KeyError deep in the phase loop.
        enemies = [
            {
                "id": "hollow_rend_1",
                "action_pool": [{"name": "Hollow Shriek", "applies_condition": "frightened", "dc": 12}],
            }
        ]
        with pytest.raises(ValueError, match="save"):
            _validate_enemy_action_conditions(enemies)

    def test_missing_or_nonint_dc_raises_at_load(self):
        enemies = [
            {
                "id": "hollow_rend_1",
                "action_pool": [{"name": "Hollow Shriek", "applies_condition": "frightened", "save": "wisdom"}],
            }
        ]
        with pytest.raises(ValueError, match="dc"):
            _validate_enemy_action_conditions(enemies)

    def test_invalid_save_attribute_raises_at_load(self):
        enemies = [
            {
                "id": "hollow_rend_1",
                "action_pool": [{"name": "Hollow Shriek", "applies_condition": "frightened", "save": "luck", "dc": 12}],
            }
        ]
        with pytest.raises(ValueError, match="save"):
            _validate_enemy_action_conditions(enemies)

    def test_abbreviated_save_key_is_accepted(self):
        # The resolver expands "wis" -> "wisdom" (roll_participant_save), so the load-gate must
        # accept the same abbreviated form — else content the engine could run fails loud at start.
        enemies = [
            {
                "id": "hollow_rend_1",
                "action_pool": [{"name": "Hollow Shriek", "applies_condition": "frightened", "save": "wis", "dc": 12}],
            }
        ]
        _validate_enemy_action_conditions(enemies)  # no raise

    def test_damage_bearing_condition_action_raises_at_load(self):
        # M13 condition actions are save-based; the resolver does not apply damage, so a non-zero
        # damage on a condition action must fail loud at load (debt 5b18023ef5a5) rather than silently
        # deal none.
        enemies = [
            {
                "id": "venom_spider",
                "action_pool": [
                    {"name": "Venom Bite", "applies_condition": "poisoned", "save": "con", "dc": 12, "damage": "2d6"}
                ],
            }
        ]
        with pytest.raises(ValueError, match="save-based"):
            _validate_enemy_action_conditions(enemies)

    def test_zero_damage_condition_action_does_not_raise(self):
        enemies = [
            {
                "id": "hollow_rend_1",
                "action_pool": [
                    {
                        "name": "Hollow Shriek",
                        "applies_condition": "frightened",
                        "save": "wisdom",
                        "dc": 12,
                        "damage": "0",
                    }
                ],
            }
        ]
        _validate_enemy_action_conditions(enemies)  # no raise

    def test_action_with_no_applies_condition_does_not_raise(self):
        enemies = [
            {
                "id": "bandit_1",
                "action_pool": [
                    {"name": "Short Sword", "damage": "1d6+2"},
                ],
            }
        ]
        _validate_enemy_action_conditions(enemies)  # no raise
