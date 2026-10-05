"""Tests for resolve_saving_throw: proficiency, effect-on-fail, crits, dramatic fields.

Extracted from test_rules_resolution.py (file-size split, debt e69251d2f945) to
keep that file under the 500-line cap.
"""

import random

import pytest
from test_rules_core import SAMPLE_PLAYER

from check_resolution_save import SavingThrowResult, resolve_saving_throw


class TestResolveSavingThrow:
    def test_success(self):
        seed = 0
        rng = random.Random(seed)
        result = resolve_saving_throw(SAMPLE_PLAYER, "strength", 13, "knocked prone", rng=rng)
        assert result.success is True
        assert result.effect_applied is None

    def test_failure_applies_effect(self):
        seed = 0
        rng = random.Random(seed)
        result = resolve_saving_throw(SAMPLE_PLAYER, "charisma", 13, "charmed", rng=rng)
        assert result.success is False
        assert result.effect_applied == "charmed"

    def test_role_dc_mod_raises_the_dc(self):
        # M4.7 story-001: a Boss ability's flat dc_mod makes its TARGET's save harder. STR save mod
        # +3; a roll that clears dc=10 (total in [10,14]) fails once dc_mod=+5 lifts the DC to 15.
        seed = 3
        base = resolve_saving_throw(SAMPLE_PLAYER, "strength", 10, "prone", rng=random.Random(seed))
        harder = resolve_saving_throw(SAMPLE_PLAYER, "strength", 10, "prone", rng=random.Random(seed), dc_mod=5)
        assert base.success is True
        assert harder.success is False
        assert harder.dc == 15  # packet reports the effective DC

    def test_dc_mod_defaults_to_identity(self):
        result = resolve_saving_throw(SAMPLE_PLAYER, "strength", 13, "prone", rng=random.Random(0))
        identity = resolve_saving_throw(SAMPLE_PLAYER, "strength", 13, "prone", rng=random.Random(0), dc_mod=0)
        assert result.dc == identity.dc == 13
        assert result.success == identity.success

    def test_nat_20_always_succeeds(self):
        seed = 5
        rng = random.Random(seed)
        result = resolve_saving_throw(SAMPLE_PLAYER, "charisma", 25, "stunned", rng=rng)
        assert result.success is True
        assert result.effect_applied is None
        assert result.critical_success is True
        assert result.critical_failure is False

    def test_nat_1_always_fails(self):
        seed = 31
        rng = random.Random(seed)
        result = resolve_saving_throw(SAMPLE_PLAYER, "strength", 1, "frightened", rng=rng)
        assert result.success is False
        assert result.effect_applied == "frightened"
        assert result.critical_failure is True
        assert result.critical_success is False

    def test_normal_roll_no_critical_flags(self):
        seed = 0
        rng = random.Random(seed)
        result = resolve_saving_throw(SAMPLE_PLAYER, "strength", 13, "knocked prone", rng=rng)
        assert isinstance(result, SavingThrowResult)
        assert result.critical_success is False
        assert result.critical_failure is False

    def test_all_six_attributes(self):
        for attr in ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]:
            rng = random.Random(42)
            result = resolve_saving_throw(SAMPLE_PLAYER, attr, 10, "effect", rng=rng)
            assert result.save_type == attr

    def test_unknown_save_type_raises(self):
        with pytest.raises(ValueError, match="Unknown save type"):
            resolve_saving_throw(SAMPLE_PLAYER, "luck", 10, "bad stuff")

    def test_proficient_save_bonus(self):
        # Strength is a proficient save
        rng = random.Random(42)
        result = resolve_saving_throw(SAMPLE_PLAYER, "strength", 10, "effect", rng=rng)
        # STR +2, prof +1 at L1 = +3
        assert result.modifier == 3

    def test_unproficient_save(self):
        rng = random.Random(42)
        result = resolve_saving_throw(SAMPLE_PLAYER, "charisma", 10, "effect", rng=rng)
        # CHA -1, no prof
        assert result.modifier == -1

    def test_nat_20_is_dramatic(self):
        seed = 5
        rng = random.Random(seed)
        result = resolve_saving_throw(SAMPLE_PLAYER, "charisma", 25, "stunned", rng=rng)
        assert result.dramatic is True
        assert result.context == "natural_20"

    def test_nat_1_is_dramatic(self):
        seed = 31
        rng = random.Random(seed)
        result = resolve_saving_throw(SAMPLE_PLAYER, "strength", 1, "frightened", rng=rng)
        assert result.dramatic is True
        assert result.context == "natural_1"

    def test_ordinary_save_not_dramatic(self):
        # A generic save is dramatic ONLY on nat 1/20 (no roll_type passed).
        seed = 0
        rng = random.Random(seed)
        result = resolve_saving_throw(SAMPLE_PLAYER, "strength", 13, "knocked prone", rng=rng)
        assert result.dramatic is False
        assert result.context == ""
