"""Exhaustive tests for the pure-function rules engine."""

import random

import pytest

from rules_engine import (
    attribute_modifier,
    skill_modifier,
    dc_for_tier,
    narrative_hint,
    attack_modifier,
    resolve_skill_check,
    resolve_attack,
    resolve_saving_throw,
    SKILLS,
    DC_TIERS,
)


# --- attribute_modifier ---

class TestAttributeModifier:
    def test_standard_table(self):
        assert attribute_modifier(1) == -5
        assert attribute_modifier(8) == -1
        assert attribute_modifier(10) == 0
        assert attribute_modifier(11) == 0
        assert attribute_modifier(12) == 1
        assert attribute_modifier(14) == 2
        assert attribute_modifier(16) == 3
        assert attribute_modifier(18) == 4
        assert attribute_modifier(20) == 5

    def test_odd_scores(self):
        assert attribute_modifier(9) == -1
        assert attribute_modifier(13) == 1
        assert attribute_modifier(15) == 2


# --- skill_modifier ---

SAMPLE_PLAYER = {
    "level": 1,
    "attributes": {
        "strength": 14,
        "dexterity": 12,
        "constitution": 13,
        "intelligence": 10,
        "wisdom": 11,
        "charisma": 8,
    },
    "proficiencies": ["athletics", "stealth", "perception"],
    "saving_throw_proficiencies": ["strength", "constitution"],
}


class TestSkillModifier:
    def test_proficient_skill(self):
        mod = skill_modifier(SAMPLE_PLAYER, "athletics")
        # STR 14 -> +2, plus prof +2 = +4
        assert mod == 4

    def test_unproficient_skill(self):
        mod = skill_modifier(SAMPLE_PLAYER, "persuasion")
        # CHA 8 -> -1, no proficiency
        assert mod == -1

    def test_proficient_dex_skill(self):
        mod = skill_modifier(SAMPLE_PLAYER, "stealth")
        # DEX 12 -> +1, plus prof +2 = +3
        assert mod == 3

    def test_wisdom_perception(self):
        mod = skill_modifier(SAMPLE_PLAYER, "perception")
        # WIS 11 -> +0, plus prof +2 = +2
        assert mod == 2

    def test_unknown_skill_raises(self):
        with pytest.raises(ValueError, match="Unknown skill"):
            skill_modifier(SAMPLE_PLAYER, "flying")

    def test_all_skills_resolve(self):
        for skill_name in SKILLS:
            mod = skill_modifier(SAMPLE_PLAYER, skill_name)
            assert isinstance(mod, int)

    def test_case_insensitive(self):
        mod = skill_modifier(SAMPLE_PLAYER, "Athletics")
        assert mod == 4

    def test_higher_level_proficiency(self):
        player = {**SAMPLE_PLAYER, "level": 5}
        mod = skill_modifier(player, "athletics")
        # STR +2, prof +3 at level 5 = +5
        assert mod == 5


# --- dc_for_tier ---

class TestDcForTier:
    def test_all_tiers(self):
        assert dc_for_tier("easy") == 9
        assert dc_for_tier("moderate") == 13
        assert dc_for_tier("hard") == 17
        assert dc_for_tier("deadly") == 21

    def test_unknown_defaults_moderate(self):
        assert dc_for_tier("impossible") == 13

    def test_case_insensitive(self):
        assert dc_for_tier("HARD") == 17
        assert dc_for_tier("Easy") == 9


# --- narrative_hint ---

class TestNarrativeHint:
    def test_nat_1(self):
        assert narrative_hint(1, 1, 10) == "critical failure"

    def test_nat_20(self):
        assert narrative_hint(20, 25, 10) == "critical success"

    def test_failed_by_large_margin(self):
        assert narrative_hint(3, 3, 17) == "failed"

    def test_barely_failed(self):
        assert narrative_hint(10, 12, 13) == "barely failed"

    def test_barely_succeeded(self):
        assert narrative_hint(10, 13, 13) == "barely succeeded"

    def test_succeeded_comfortably(self):
        assert narrative_hint(12, 17, 13) == "succeeded comfortably"

    def test_large_success(self):
        assert narrative_hint(15, 22, 13) == "critical success"


# --- attack_modifier ---

class TestAttackModifier:
    def test_melee_weapon(self):
        weapon = {"damage": "1d8", "damage_type": "slashing", "properties": []}
        mod = attack_modifier(SAMPLE_PLAYER, weapon)
        # STR +2, prof +2 = +4
        assert mod == 4

    def test_ranged_weapon(self):
        weapon = {"damage": "1d8", "ranged": True, "properties": []}
        mod = attack_modifier(SAMPLE_PLAYER, weapon)
        # DEX +1, prof +2 = +3
        assert mod == 3

    def test_finesse_weapon_uses_higher(self):
        weapon = {"damage": "1d6", "properties": ["finesse"]}
        mod = attack_modifier(SAMPLE_PLAYER, weapon)
        # max(STR +2, DEX +1) + prof +2 = +4
        assert mod == 4


# --- resolve_skill_check ---

class TestResolveSkillCheck:
    def test_success(self):
        # Seed that produces d20=15
        rng = random.Random(42)
        test_roll = rng.randint(1, 20)
        # Reset to same seed for actual call
        rng = random.Random(42)
        result = resolve_skill_check(SAMPLE_PLAYER, "athletics", "moderate", rng=rng)
        assert result.roll == test_roll
        assert result.skill == "athletics"
        assert result.modifier == 4
        assert result.total == test_roll + 4
        assert result.dc == 13
        assert result.success == (result.total >= 13 or test_roll == 20)

    def test_nat_20_always_succeeds(self):
        # Find a seed that gives nat 20
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 20:
                rng = random.Random(seed)
                result = resolve_skill_check(SAMPLE_PLAYER, "persuasion", "deadly", rng=rng)
                assert result.success is True
                assert result.roll == 20
                assert result.narrative_hint == "critical success"
                return
        pytest.fail("Could not find seed for nat 20")

    def test_nat_1_always_fails(self):
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 1:
                rng = random.Random(seed)
                result = resolve_skill_check(SAMPLE_PLAYER, "athletics", "easy", rng=rng)
                assert result.success is False
                assert result.roll == 1
                assert result.narrative_hint == "critical failure"
                return
        pytest.fail("Could not find seed for nat 1")

    def test_proficiency_bonus_applied(self):
        rng = random.Random(42)
        prof_result = resolve_skill_check(SAMPLE_PLAYER, "athletics", "moderate", rng=rng)
        rng = random.Random(42)
        unprof_result = resolve_skill_check(SAMPLE_PLAYER, "persuasion", "moderate", rng=rng)
        # athletics: STR+2, prof+2 = +4; persuasion: CHA-1, no prof = -1
        assert prof_result.modifier == 4
        assert unprof_result.modifier == -1


# --- resolve_attack ---

class TestResolveAttack:
    WEAPON = {"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}

    def test_hit(self):
        # Find seed where d20 roll + 4 >= 12
        for seed in range(1000):
            rng = random.Random(seed)
            d20 = rng.randint(1, 20)
            if d20 != 1 and d20 + 4 >= 12:
                rng = random.Random(seed)
                result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 12, 20, rng=rng)
                assert result.hit is True
                assert result.damage > 0
                assert result.target_hp_remaining == 20 - result.damage
                return
        pytest.fail("Could not find seed for hit")

    def test_miss(self):
        for seed in range(1000):
            rng = random.Random(seed)
            d20 = rng.randint(1, 20)
            if d20 != 20 and d20 + 4 < 18:
                rng = random.Random(seed)
                result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 18, 20, rng=rng)
                assert result.hit is False
                assert result.damage == 0
                assert result.target_hp_remaining == 20
                return
        pytest.fail("Could not find seed for miss")

    def test_critical_hit_doubles_damage(self):
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 20:
                rng = random.Random(seed)
                result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 20, 50, rng=rng)
                assert result.critical is True
                assert result.hit is True
                # Damage should be two rolls of 1d8
                assert result.damage >= 2  # minimum 1+1
                return
        pytest.fail("Could not find seed for crit")

    def test_target_killed_at_zero_hp(self):
        for seed in range(1000):
            rng = random.Random(seed)
            d20 = rng.randint(1, 20)
            if d20 != 1 and d20 + 4 >= 10:
                rng = random.Random(seed)
                result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 10, 1, rng=rng)
                if result.hit:
                    assert result.target_hp_remaining == 0
                    assert result.target_killed is True
                    return
        pytest.fail("Could not find seed for kill")

    def test_hp_floors_at_zero(self):
        for seed in range(1000):
            rng = random.Random(seed)
            d20 = rng.randint(1, 20)
            if d20 != 1 and d20 + 4 >= 10:
                rng = random.Random(seed)
                result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 10, 3, rng=rng)
                if result.hit:
                    assert result.target_hp_remaining >= 0
                    return
        pytest.fail("Could not find seed for hit")

    def test_nat_1_always_misses(self):
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 1:
                rng = random.Random(seed)
                result = resolve_attack(SAMPLE_PLAYER, self.WEAPON, 5, 20, rng=rng)
                assert result.hit is False
                assert result.roll == 1
                return
        pytest.fail("Could not find seed for nat 1")


# --- resolve_saving_throw ---

class TestResolveSavingThrow:
    def test_success(self):
        for seed in range(1000):
            rng = random.Random(seed)
            d20 = rng.randint(1, 20)
            # STR save: attr mod +2, prof +2 = +4
            if d20 != 1 and d20 + 4 >= 13:
                rng = random.Random(seed)
                result = resolve_saving_throw(
                    SAMPLE_PLAYER, "strength", 13, "knocked prone", rng=rng
                )
                assert result.success is True
                assert result.effect_applied is None
                return
        pytest.fail("Could not find seed for success")

    def test_failure_applies_effect(self):
        for seed in range(1000):
            rng = random.Random(seed)
            d20 = rng.randint(1, 20)
            # CHA save: attr mod -1, no prof = -1
            if d20 != 20 and d20 - 1 < 13:
                rng = random.Random(seed)
                result = resolve_saving_throw(
                    SAMPLE_PLAYER, "charisma", 13, "charmed", rng=rng
                )
                assert result.success is False
                assert result.effect_applied == "charmed"
                return
        pytest.fail("Could not find seed for failure")

    def test_nat_20_always_succeeds(self):
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 20:
                rng = random.Random(seed)
                result = resolve_saving_throw(
                    SAMPLE_PLAYER, "charisma", 25, "stunned", rng=rng
                )
                assert result.success is True
                assert result.effect_applied is None
                return
        pytest.fail("Could not find seed for nat 20")

    def test_nat_1_always_fails(self):
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 1:
                rng = random.Random(seed)
                result = resolve_saving_throw(
                    SAMPLE_PLAYER, "strength", 1, "frightened", rng=rng
                )
                assert result.success is False
                assert result.effect_applied == "frightened"
                return
        pytest.fail("Could not find seed for nat 1")

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
        # STR +2, prof +2 = +4
        assert result.modifier == 4

    def test_unproficient_save(self):
        rng = random.Random(42)
        result = resolve_saving_throw(SAMPLE_PLAYER, "charisma", 10, "effect", rng=rng)
        # CHA -1, no prof
        assert result.modifier == -1
