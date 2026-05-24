"""Tests for recipe_study async-cycle coupling (story-006 Slice D, AC5).

The async cost to learn a recipe via recipe_study training scales with the
recipe's tier (Basic 1 / Trained 2 / Expert 4 / Master 6, spec §Recipe
Acquisition). The policy lives in the recipe_study entry's tier_cycles map in
content/training_activity_types.json and resolves via get_recipe_study_cycles —
NOT recipe.study_cost (assumption 0fa7c3e953bd).
"""

import json
from pathlib import Path

import pytest

import training_rules

_CONTENT = Path(__file__).resolve().parents[3] / "content" / "training_activity_types.json"
_SPEC_CYCLES = {"basic": 1, "trained": 2, "expert": 4, "master": 6}


class TestParseRecipeStudyCycles:
    def test_valid_map_parses(self):
        assert training_rules.parse_recipe_study_cycles({"tier_cycles": _SPEC_CYCLES}) == _SPEC_CYCLES

    def test_missing_map_fails_loud(self):
        with pytest.raises(ValueError, match="tier_cycles"):
            training_rules.parse_recipe_study_cycles({})

    def test_missing_tier_fails_loud(self):
        with pytest.raises(ValueError, match="master"):
            training_rules.parse_recipe_study_cycles({"tier_cycles": {"basic": 1, "trained": 2, "expert": 4}})

    def test_rejects_non_positive(self):
        with pytest.raises(ValueError, match="basic"):
            training_rules.parse_recipe_study_cycles({"tier_cycles": {**_SPEC_CYCLES, "basic": 0}})

    def test_rejects_bool(self):
        # bool is an int subclass — must not pass as a cycle count.
        with pytest.raises(ValueError, match="trained"):
            training_rules.parse_recipe_study_cycles({"tier_cycles": {**_SPEC_CYCLES, "trained": True}})


class TestGetRecipeStudyCycles:
    def test_resolves_each_tier_after_set(self):
        training_rules.set_recipe_study_cycles(dict(_SPEC_CYCLES))
        assert training_rules.get_recipe_study_cycles("basic") == 1
        assert training_rules.get_recipe_study_cycles("trained") == 2
        assert training_rules.get_recipe_study_cycles("expert") == 4
        assert training_rules.get_recipe_study_cycles("master") == 6

    def test_unknown_tier_fails_loud(self):
        training_rules.set_recipe_study_cycles(dict(_SPEC_CYCLES))
        with pytest.raises(ValueError, match="legendary"):
            training_rules.get_recipe_study_cycles("legendary")


class TestContentEntryReflectsTier:
    def test_recipe_study_content_encodes_spec_cycle_counts(self):
        # AC5: the seeded recipe_study entry's cycle counts reflect recipe tier.
        raw = json.loads(_CONTENT.read_text())
        recipe_study = next(e for e in raw if e["id"] == "recipe_study")
        assert training_rules.parse_recipe_study_cycles(recipe_study) == _SPEC_CYCLES
