"""Tests for check resolution: dice checks, attacks, skill checks, saving throws."""

import random

import pytest
from test_rules_core import SAMPLE_PLAYER

from check_resolution import (
    CheckResult,
    attack_modifier,
    resolve_attack,
    resolve_check,
    resolve_saving_throw,
    resolve_skill_check,
    resolve_skill_check_dc,
)

# --- resolve_check ---


class TestResolveCheck:
    def test_returns_check_result(self):
        result = resolve_check(14, 1, "trained", 12, rng=random.Random(42))
        assert isinstance(result, CheckResult)

    def test_trained_modifier_components(self):
        # attr 14 → mod +2, level 1 → prof +1, trained → tier +2 = total +5
        result = resolve_check(14, 1, "trained", 12, rng=random.Random(42))
        assert result.modifier == 5
        assert result.dc == 12

    def test_untrained_no_prof_no_tier(self):
        # attr 10 → mod +0, untrained → no prof, no tier = total +0
        result = resolve_check(10, 1, "untrained", 12, rng=random.Random(42))
        assert result.modifier == 0

    def test_expert_modifier(self):
        # attr 16 → mod +3, level 7 → prof +2, expert → tier +4 = total +9
        result = resolve_check(16, 7, "expert", 20, rng=random.Random(42))
        assert result.modifier == 9

    def test_master_modifier(self):
        # attr 18 → mod +4, level 14 → prof +3, master → tier +5 = total +12
        result = resolve_check(18, 14, "master", 28, rng=random.Random(42))
        assert result.modifier == 12

    def test_success_when_total_meets_dc(self):
        # Find seed where roll + 5 >= 12 (and not nat 1)
        for seed in range(1000):
            rng = random.Random(seed)
            d20 = rng.randint(1, 20)
            if d20 != 1 and d20 + 5 >= 12:
                rng = random.Random(seed)
                result = resolve_check(14, 1, "trained", 12, rng=rng)
                assert result.success is True
                assert result.total == d20 + 5
                return
        pytest.fail("Could not find seed for success")

    def test_failure_when_total_below_dc(self):
        for seed in range(1000):
            rng = random.Random(seed)
            d20 = rng.randint(1, 20)
            if d20 != 20 and d20 + 0 < 16:
                rng = random.Random(seed)
                result = resolve_check(10, 1, "untrained", 16, rng=rng)
                assert result.success is False
                return
        pytest.fail("Could not find seed for failure")

    def test_nat_20_always_succeeds(self):
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 20:
                rng = random.Random(seed)
                result = resolve_check(8, 1, "untrained", 20, rng=rng)
                assert result.success is True
                assert result.roll == 20
                assert result.critical_success is True
                return
        pytest.fail("Could not find seed for nat 20")

    def test_nat_1_always_fails(self):
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 1:
                rng = random.Random(seed)
                result = resolve_check(20, 14, "master", 5, rng=rng)
                assert result.success is False
                assert result.roll == 1
                assert result.critical_failure is True
                return
        pytest.fail("Could not find seed for nat 1")

    def test_auto_fail_untrained_dc24(self):
        result = resolve_check(14, 1, "untrained", 24, rng=random.Random(42))
        assert result.auto_fail is True
        assert result.success is False

    def test_auto_fail_trained_dc24(self):
        result = resolve_check(14, 7, "trained", 24, rng=random.Random(42))
        assert result.auto_fail is True
        assert result.success is False

    def test_expert_can_attempt_dc24(self):
        result = resolve_check(16, 7, "expert", 24, rng=random.Random(42))
        assert result.auto_fail is False

    def test_auto_fail_expert_dc28(self):
        result = resolve_check(16, 7, "expert", 28, rng=random.Random(42))
        assert result.auto_fail is True
        assert result.success is False

    def test_master_can_attempt_dc28(self):
        result = resolve_check(18, 14, "master", 28, rng=random.Random(42))
        assert result.auto_fail is False

    def test_auto_fail_overrides_nat20(self):
        # Even nat 20 cannot overcome a tier gate
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 20:
                rng = random.Random(seed)
                result = resolve_check(14, 1, "untrained", 24, rng=rng)
                assert result.auto_fail is True
                assert result.success is False
                return
        pytest.fail("Could not find seed for nat 20")

    def test_margin_calculation(self):
        for seed in range(1000):
            rng = random.Random(seed)
            d20 = rng.randint(1, 20)
            if 5 <= d20 <= 15:  # avoid crits
                rng = random.Random(seed)
                result = resolve_check(14, 1, "trained", 12, rng=rng)
                assert result.margin == result.total - result.dc
                return
        pytest.fail("Could not find suitable seed")

    def test_critical_flags(self):
        # Non-crit roll should have both flags False
        for seed in range(1000):
            rng = random.Random(seed)
            d20 = rng.randint(1, 20)
            if 2 <= d20 <= 19:
                rng = random.Random(seed)
                result = resolve_check(14, 1, "trained", 12, rng=rng)
                assert result.critical_success is False
                assert result.critical_failure is False
                return
        pytest.fail("Could not find non-crit seed")

    def test_narrative_hint_present(self):
        result = resolve_check(14, 1, "trained", 12, rng=random.Random(42))
        assert isinstance(result.narrative_hint, str)
        assert len(result.narrative_hint) > 0

    def test_auto_fail_narrative(self):
        result = resolve_check(10, 1, "untrained", 24, rng=random.Random(42))
        assert result.auto_fail is True
        assert "beyond" in result.narrative_hint.lower() or "impossible" in result.narrative_hint.lower()

    def test_deterministic_with_rng(self):
        a = resolve_check(14, 1, "trained", 12, rng=random.Random(99))
        b = resolve_check(14, 1, "trained", 12, rng=random.Random(99))
        assert a == b


# --- attack_modifier ---


class TestAttackModifier:
    def test_melee_weapon(self):
        weapon = {"damage": "1d8", "damage_type": "slashing", "properties": []}
        mod = attack_modifier(SAMPLE_PLAYER, weapon)
        # STR +2, prof +1 at L1 = +3
        assert mod == 3

    def test_ranged_weapon(self):
        weapon = {"damage": "1d8", "ranged": True, "properties": []}
        mod = attack_modifier(SAMPLE_PLAYER, weapon)
        # DEX +1, prof +1 at L1 = +2
        assert mod == 2

    def test_finesse_weapon_uses_higher(self):
        weapon = {"damage": "1d6", "properties": ["finesse"]}
        mod = attack_modifier(SAMPLE_PLAYER, weapon)
        # max(STR +2, DEX +1) + prof +1 at L1 = +3
        assert mod == 3


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
        assert result.modifier == 5  # STR +2, trained: prof +1 + tier +2
        assert result.total == test_roll + 5
        assert result.dc == 12  # moderate = 12
        assert result.success == (result.total >= 12 or test_roll == 20)

    def test_nat_20_always_succeeds(self):
        # Find a seed that gives nat 20. Use very_hard (DC 20) to avoid auto-fail for untrained.
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 20:
                rng = random.Random(seed)
                result = resolve_skill_check(SAMPLE_PLAYER, "persuasion", "very_hard", rng=rng)
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
        # athletics: STR+2, trained(prof+1, tier+2) = +5; persuasion: CHA-1, untrained = -1
        assert prof_result.modifier == 5
        assert unprof_result.modifier == -1


# --- resolve_skill_check_dc ---


class TestResolveSkillCheckDc:
    def test_success_with_numeric_dc(self):
        rng = random.Random(42)
        result = resolve_skill_check_dc(SAMPLE_PLAYER, "athletics", 10, rng=rng)
        assert result.dc == 10
        assert result.skill == "athletics"
        assert result.modifier == 5  # STR +2, trained: prof +1 + tier +2

    def test_failure_with_high_dc(self):
        for seed in range(1000):
            rng = random.Random(seed)
            d20 = rng.randint(1, 20)
            # athletics mod = +4, need total < 25, so d20 < 21 (always true except nat20)
            if d20 != 20 and d20 + 4 < 25:
                rng = random.Random(seed)
                result = resolve_skill_check_dc(SAMPLE_PLAYER, "athletics", 25, rng=rng)
                assert result.success is False
                assert result.dc == 25
                return
        pytest.fail("Could not find seed for failure")

    def test_nat_20_always_succeeds(self):
        # Use DC 23 to avoid auto-fail for trained perception (auto-fail at DC 24+)
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 20:
                rng = random.Random(seed)
                result = resolve_skill_check_dc(SAMPLE_PLAYER, "perception", 23, rng=rng)
                assert result.success is True
                assert result.roll == 20
                return
        pytest.fail("Could not find seed for nat 20")

    def test_nat_1_always_fails(self):
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 1:
                rng = random.Random(seed)
                result = resolve_skill_check_dc(SAMPLE_PLAYER, "athletics", 1, rng=rng)
                assert result.success is False
                assert result.roll == 1
                return
        pytest.fail("Could not find seed for nat 1")

    def test_uses_numeric_dc_not_tier(self):
        rng = random.Random(42)
        dc_result = resolve_skill_check_dc(SAMPLE_PLAYER, "athletics", 14, rng=rng)
        assert dc_result.dc == 14
        rng = random.Random(42)
        tier_result = resolve_skill_check(SAMPLE_PLAYER, "athletics", "moderate", rng=rng)
        assert tier_result.dc == 12  # moderate = 12, not 14
        assert dc_result.dc != tier_result.dc

    def test_proficiency_applied(self):
        rng = random.Random(42)
        result = resolve_skill_check_dc(SAMPLE_PLAYER, "perception", 10, rng=rng)
        # WIS 11 → +0, trained: prof +1 + tier +2 = +3
        assert result.modifier == 3


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
            # STR save: attr mod +2, prof +1 at L1 = +3
            if d20 != 1 and d20 + 3 >= 13:
                rng = random.Random(seed)
                result = resolve_saving_throw(SAMPLE_PLAYER, "strength", 13, "knocked prone", rng=rng)
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
                result = resolve_saving_throw(SAMPLE_PLAYER, "charisma", 13, "charmed", rng=rng)
                assert result.success is False
                assert result.effect_applied == "charmed"
                return
        pytest.fail("Could not find seed for failure")

    def test_nat_20_always_succeeds(self):
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 20:
                rng = random.Random(seed)
                result = resolve_saving_throw(SAMPLE_PLAYER, "charisma", 25, "stunned", rng=rng)
                assert result.success is True
                assert result.effect_applied is None
                return
        pytest.fail("Could not find seed for nat 20")

    def test_nat_1_always_fails(self):
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 1:
                rng = random.Random(seed)
                result = resolve_saving_throw(SAMPLE_PLAYER, "strength", 1, "frightened", rng=rng)
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
        # STR +2, prof +1 at L1 = +3
        assert result.modifier == 3

    def test_unproficient_save(self):
        rng = random.Random(42)
        result = resolve_saving_throw(SAMPLE_PLAYER, "charisma", 10, "effect", rng=rng)
        # CHA -1, no prof
        assert result.modifier == -1
