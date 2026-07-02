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

    def test_known_hostile_condition_does_not_raise(self):
        enemies = [
            {
                "id": "hollow_rend_1",
                "action_pool": [
                    {"name": "Hollow Shriek", "applies_condition": "frightened"},
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
