"""Exhaustive tests for the pure-function rules engine."""

import random

import pytest

from check_resolution import (
    AdvancementResult,
    CheckResult,
    SkillCapabilities,
    attack_modifier,
    check_skill_capabilities,
    record_skill_use,
    resolve_attack,
    resolve_check,
    resolve_saving_throw,
    resolve_skill_check,
    resolve_skill_check_dc,
)
from combat_resolution import (
    calculate_combat_xp,
    hp_threshold_status,
    resolve_death_save,
    roll_initiative,
)
from rules_engine import (
    ADVANCEMENT_THRESHOLDS,
    ARCHETYPE_RESOURCE_CONFIG,
    DC_TIERS,
    SKILL_CAPABILITIES,
    SKILL_TIER_BONUS,
    SKILL_TIER_ORDER,
    SKILLS,
    XP_FOR_LEVEL,
    DcTier,
    PoolFormula,
    PoolMaximums,
    SkillTier,
    attribute_modifier,
    calculate_max_pools,
    check_level_up,
    dc_for_tier,
    narrative_hint,
    proficiency_bonus,
    skill_modifier,
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
        # STR 14 → +2, trained: prof +1 + tier +2 = +5
        assert mod == 5

    def test_unproficient_skill(self):
        mod = skill_modifier(SAMPLE_PLAYER, "persuasion")
        # CHA 8 → -1, untrained: no prof, no tier = -1
        assert mod == -1

    def test_proficient_dex_skill(self):
        mod = skill_modifier(SAMPLE_PLAYER, "stealth")
        # DEX 12 → +1, trained: prof +1 + tier +2 = +4
        assert mod == 4

    def test_wisdom_perception(self):
        mod = skill_modifier(SAMPLE_PLAYER, "perception")
        # WIS 11 → +0, trained: prof +1 + tier +2 = +3
        assert mod == 3

    def test_unknown_skill_raises(self):
        with pytest.raises(ValueError, match="Unknown skill"):
            skill_modifier(SAMPLE_PLAYER, "flying")

    def test_all_skills_resolve(self):
        for skill_name in SKILLS:
            mod = skill_modifier(SAMPLE_PLAYER, skill_name)
            assert isinstance(mod, int)

    def test_case_insensitive(self):
        mod = skill_modifier(SAMPLE_PLAYER, "Athletics")
        # STR 14 → +2, trained: prof +1 + tier +2 = +5
        assert mod == 5

    def test_higher_level_proficiency(self):
        player = {**SAMPLE_PLAYER, "level": 7}
        mod = skill_modifier(player, "athletics")
        # STR +2, trained: prof +2 at L7 + tier +2 = +6
        assert mod == 6

    def test_crafting_uses_max_attribute(self):
        # INT 10 → +0, WIS 11 → +0. max(+0, +0) = 0. Untrained = 0
        mod = skill_modifier(SAMPLE_PLAYER, "crafting")
        assert mod == 0
        # Player with higher WIS
        player = {**SAMPLE_PLAYER, "attributes": {**SAMPLE_PLAYER["attributes"], "wisdom": 16}}
        mod = skill_modifier(player, "crafting")
        # max(INT +0, WIS +3) = +3. Untrained = +3 (no prof, no tier)
        assert mod == 3

    def test_skill_tier_from_player_data(self):
        # Player with explicit skill_tiers
        player = {**SAMPLE_PLAYER, "skill_tiers": {"athletics": "expert"}}
        mod = skill_modifier(player, "athletics")
        # STR +2, expert: prof +1 + tier +4 = +7
        assert mod == 7

    def test_untrained_gets_no_prof_or_tier(self):
        mod = skill_modifier(SAMPLE_PLAYER, "arcana")
        # INT 10 → +0, not in proficiencies, untrained: no prof, no tier = 0
        assert mod == 0


# --- skills ---


class TestSkills:
    def test_has_20_skills(self):
        assert len(SKILLS) == 20

    def test_physical_skills(self):
        assert SKILLS["athletics"] == "strength"
        assert SKILLS["acrobatics"] == "dexterity"
        assert SKILLS["stealth"] == "dexterity"
        assert SKILLS["sleight_of_hand"] == "dexterity"
        assert SKILLS["endurance"] == "constitution"

    def test_mental_skills(self):
        assert SKILLS["arcana"] == "intelligence"
        assert SKILLS["history"] == "intelligence"
        assert SKILLS["investigation"] == "intelligence"
        assert SKILLS["nature"] == "intelligence"
        assert SKILLS["religion"] == "intelligence"
        assert SKILLS["medicine"] == "wisdom"
        assert SKILLS["perception"] == "wisdom"
        assert SKILLS["survival"] == "wisdom"
        assert SKILLS["insight"] == "wisdom"
        assert SKILLS["animal_handling"] == "wisdom"

    def test_social_skills(self):
        assert SKILLS["persuasion"] == "charisma"
        assert SKILLS["deception"] == "charisma"
        assert SKILLS["intimidation"] == "charisma"
        assert SKILLS["performance"] == "charisma"

    def test_crafting_is_multi_attribute(self):
        assert SKILLS["crafting"] == ("intelligence", "wisdom")


# --- dc_for_tier ---


class TestDcForTier:
    def test_all_tiers(self):
        assert dc_for_tier("trivial") == 5
        assert dc_for_tier("easy") == 8
        assert dc_for_tier("moderate") == 12
        assert dc_for_tier("hard") == 16
        assert dc_for_tier("very_hard") == 20
        assert dc_for_tier("extreme") == 24
        assert dc_for_tier("legendary") == 28

    def test_deadly_alias(self):
        assert dc_for_tier("deadly") == 24

    def test_unknown_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown difficulty tier"):
            dc_for_tier("impossible")

    def test_case_insensitive(self):
        assert dc_for_tier("HARD") == 16
        assert dc_for_tier("Easy") == 8

    def test_dc_tiers_dict_has_all_entries(self):
        assert len(DC_TIERS) == 8  # 7 canonical + 1 deprecated alias


# --- type aliases ---


class TestTypeAliases:
    def test_dc_tier_type_exists(self):
        # DcTier should be a Literal type alias importable from rules_engine
        assert DcTier is not None

    def test_skill_tier_type_exists(self):
        # SkillTier should be a Literal type alias importable from rules_engine
        assert SkillTier is not None


# --- proficiency_bonus ---


class TestProficiencyBonus:
    def test_levels_1_through_6(self):
        for level in range(1, 7):
            assert proficiency_bonus(level) == 1, f"Level {level} should give +1"

    def test_levels_7_through_13(self):
        for level in range(7, 14):
            assert proficiency_bonus(level) == 2, f"Level {level} should give +2"

    def test_levels_14_through_20(self):
        for level in range(14, 21):
            assert proficiency_bonus(level) == 3, f"Level {level} should give +3"

    def test_breakpoints(self):
        assert proficiency_bonus(6) == 1
        assert proficiency_bonus(7) == 2
        assert proficiency_bonus(13) == 2
        assert proficiency_bonus(14) == 3


# --- skill_tier_bonus ---


class TestSkillTierBonus:
    def test_all_tiers(self):
        assert SKILL_TIER_BONUS["untrained"] == 0
        assert SKILL_TIER_BONUS["trained"] == 2
        assert SKILL_TIER_BONUS["expert"] == 4
        assert SKILL_TIER_BONUS["master"] == 5

    def test_tier_order(self):
        assert SKILL_TIER_ORDER == ["untrained", "trained", "expert", "master"]

    def test_bonuses_increase_with_tier(self):
        for i in range(len(SKILL_TIER_ORDER) - 1):
            lower = SKILL_TIER_ORDER[i]
            higher = SKILL_TIER_ORDER[i + 1]
            assert SKILL_TIER_BONUS[lower] < SKILL_TIER_BONUS[higher]


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


# --- check_level_up ---


class TestCheckLevelUp:
    def test_no_level_up(self):
        result = check_level_up(current_xp=0, xp_gained=100, current_level=1)
        assert result.new_xp == 100
        assert result.new_level == 1
        assert result.leveled_up is False
        assert result.levels_gained == 0

    def test_level_up_to_2(self):
        # Canonical: L2 threshold = 200 cumulative
        result = check_level_up(current_xp=100, xp_gained=100, current_level=1)
        assert result.new_xp == 200
        assert result.new_level == 2
        assert result.leveled_up is True
        assert result.levels_gained == 1

    def test_exact_threshold(self):
        # Canonical: L2 = 200
        result = check_level_up(current_xp=0, xp_gained=200, current_level=1)
        assert result.new_level == 2

    def test_multi_level_up(self):
        # Canonical: L5 = 1050, award enough to reach L5
        result = check_level_up(current_xp=0, xp_gained=1050, current_level=1)
        assert result.new_level == 5
        assert result.levels_gained == 4

    def test_max_level_cap(self):
        # Canonical: L20 = 11250
        result = check_level_up(current_xp=11250, xp_gained=50000, current_level=20)
        assert result.new_xp == 61250
        assert result.new_level == 20
        assert result.leveled_up is False

    def test_xp_table_is_monotonic(self):
        for lvl in range(2, 21):
            assert XP_FOR_LEVEL[lvl] > XP_FOR_LEVEL[lvl - 1]

    def test_level_1_starts_at_zero(self):
        assert XP_FOR_LEVEL[1] == 0

    def test_xp_table_matches_canonical(self):
        """Verify XP table matches game_mechanics_core.md canonical values."""
        canonical = {
            1: 0,
            2: 200,
            3: 450,
            4: 750,
            5: 1050,
            6: 1450,
            7: 1900,
            8: 2400,
            9: 2900,
            10: 3450,
            11: 4050,
            12: 4650,
            13: 5300,
            14: 6000,
            15: 6750,
            16: 7550,
            17: 8400,
            18: 9300,
            19: 10250,
            20: 11250,
        }
        assert canonical == XP_FOR_LEVEL

    def test_xp_table_has_20_levels(self):
        assert len(XP_FOR_LEVEL) == 20

    # --- Attribute points ---

    def test_level_4_grants_attribute_points(self):
        # L3 → L4: attribute increase level
        result = check_level_up(current_xp=450, xp_gained=300, current_level=3)
        assert result.new_level == 4
        assert result.attribute_points == 2

    def test_level_3_no_attribute_points(self):
        # L2 → L3: not an attribute increase level
        result = check_level_up(current_xp=200, xp_gained=250, current_level=2)
        assert result.new_level == 3
        assert result.attribute_points == 0

    def test_no_level_up_no_attribute_points(self):
        result = check_level_up(current_xp=0, xp_gained=100, current_level=1)
        assert result.attribute_points == 0

    def test_multi_level_accumulates_attribute_points(self):
        # L1 → L8: crosses L4 (+2) and L8 (+2) = 4 total
        result = check_level_up(current_xp=0, xp_gained=2400, current_level=1)
        assert result.new_level == 8
        assert result.attribute_points == 4

    def test_all_attribute_increase_levels(self):
        # L1 → L20: crosses L4, L8, L12, L16, L20 = 10 total
        result = check_level_up(current_xp=0, xp_gained=11250, current_level=1)
        assert result.new_level == 20
        assert result.attribute_points == 10

    # --- Specialization fork ---

    def test_level_5_specialization_fork(self):
        # L4 → L5: specialization level
        result = check_level_up(current_xp=750, xp_gained=300, current_level=4)
        assert result.new_level == 5
        assert result.specialization_fork is True

    def test_level_4_no_fork(self):
        # L3 → L4: not specialization level
        result = check_level_up(current_xp=450, xp_gained=300, current_level=3)
        assert result.new_level == 4
        assert result.specialization_fork is False

    def test_multi_level_includes_fork(self):
        # L1 → L8: crosses L5, so fork is True
        result = check_level_up(current_xp=0, xp_gained=2400, current_level=1)
        assert result.new_level == 8
        assert result.specialization_fork is True

    def test_past_fork_no_flag(self):
        # L6 → L8: already past L5, fork is False
        result = check_level_up(current_xp=1450, xp_gained=950, current_level=6)
        assert result.new_level == 8
        assert result.specialization_fork is False


class TestLevelUpE2E:
    """E2E acceptance criteria: XP awards produce correct level-up rewards."""

    def test_cross_l4_threshold(self):
        # Award XP to go from L1 to L4 (cumulative 750)
        result = check_level_up(current_xp=0, xp_gained=750, current_level=1)
        assert result.new_level == 4
        assert result.attribute_points == 2
        assert result.specialization_fork is False

    def test_cross_l5_threshold(self):
        # Award XP to go from L4 to L5 (cumulative 1050)
        result = check_level_up(current_xp=750, xp_gained=300, current_level=4)
        assert result.new_level == 5
        assert result.attribute_points == 0
        assert result.specialization_fork is True

    def test_l1_to_l5_gets_both(self):
        # Award XP to go from L1 to L5 (cumulative 1050)
        result = check_level_up(current_xp=0, xp_gained=1050, current_level=1)
        assert result.new_level == 5
        assert result.attribute_points == 2  # from L4
        assert result.specialization_fork is True  # from L5
        assert result.levels_gained == 4


# --- roll_initiative ---


class TestRollInitiative:
    PARTICIPANTS = [
        {"id": "player_1", "name": "Kael", "attributes": {"dexterity": 14}},
        {"id": "goblin_1", "name": "Goblin A", "attributes": {"dexterity": 12}},
        {"id": "goblin_2", "name": "Goblin B", "attributes": {"dexterity": 8}},
    ]

    def test_sorted_descending(self):
        rng = random.Random(42)
        entries = roll_initiative(self.PARTICIPANTS, rng=rng)
        totals = [e.total for e in entries]
        assert totals == sorted(totals, reverse=True)

    def test_dex_modifier_applied(self):
        rng = random.Random(42)
        entries = roll_initiative(self.PARTICIPANTS, rng=rng)
        for e in entries:
            participant = next(p for p in self.PARTICIPANTS if p["id"] == e.participant_id)
            dex = participant["attributes"]["dexterity"]
            expected_mod = (dex - 10) // 2
            assert e.modifier == expected_mod
            assert e.total == e.roll + e.modifier

    def test_deterministic_with_rng(self):
        entries_a = roll_initiative(self.PARTICIPANTS, rng=random.Random(99))
        entries_b = roll_initiative(self.PARTICIPANTS, rng=random.Random(99))
        assert [e.total for e in entries_a] == [e.total for e in entries_b]

    def test_all_participants_included(self):
        rng = random.Random(42)
        entries = roll_initiative(self.PARTICIPANTS, rng=rng)
        ids = {e.participant_id for e in entries}
        assert ids == {"player_1", "goblin_1", "goblin_2"}

    def test_single_participant(self):
        entries = roll_initiative([self.PARTICIPANTS[0]], rng=random.Random(1))
        assert len(entries) == 1
        assert entries[0].participant_id == "player_1"

    def test_empty_list(self):
        entries = roll_initiative([], rng=random.Random(1))
        assert entries == []


# --- resolve_death_save ---


class TestResolveDeathSave:
    def test_success_on_10_or_higher(self):
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) >= 10:
                rng = random.Random(seed)
                result = resolve_death_save(0, 0, rng=rng)
                assert result.success is True
                assert result.total_successes == 1
                assert result.total_failures == 0
                return
        pytest.fail("Could not find seed for success")

    def test_failure_below_10(self):
        for seed in range(1000):
            rng = random.Random(seed)
            d20 = rng.randint(1, 20)
            if 2 <= d20 <= 9:
                rng = random.Random(seed)
                result = resolve_death_save(0, 0, rng=rng)
                assert result.success is False
                assert result.total_successes == 0
                assert result.total_failures == 1
                return
        pytest.fail("Could not find seed for failure")

    def test_nat_20_critical_success(self):
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 20:
                rng = random.Random(seed)
                result = resolve_death_save(0, 0, rng=rng)
                assert result.critical_success is True
                assert result.roll == 20
                assert "spark" in result.narrative_hint.lower() or "eyes open" in result.narrative_hint.lower()
                return
        pytest.fail("Could not find seed for nat 20")

    def test_nat_1_double_failure(self):
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 1:
                rng = random.Random(seed)
                result = resolve_death_save(0, 0, rng=rng)
                assert result.critical_failure is True
                assert result.total_failures == 2
                return
        pytest.fail("Could not find seed for nat 1")

    def test_stabilize_at_3_successes(self):
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) >= 10:
                rng = random.Random(seed)
                result = resolve_death_save(2, 0, rng=rng)
                assert result.stabilized is True
                assert result.total_successes >= 3
                return
        pytest.fail("Could not find seed for stabilize")

    def test_dead_at_3_failures(self):
        for seed in range(1000):
            rng = random.Random(seed)
            d20 = rng.randint(1, 20)
            if 2 <= d20 <= 9:
                rng = random.Random(seed)
                result = resolve_death_save(0, 2, rng=rng)
                assert result.dead is True
                assert result.total_failures >= 3
                return
        pytest.fail("Could not find seed for death")

    def test_nat_1_can_cause_death_from_1_failure(self):
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 1:
                rng = random.Random(seed)
                result = resolve_death_save(0, 1, rng=rng)
                assert result.dead is True
                assert result.total_failures == 3
                return
        pytest.fail("Could not find seed for nat 1")


# --- hp_threshold_status ---


class TestHpThresholdStatus:
    def test_healthy(self):
        assert hp_threshold_status(20, 20) == "healthy"
        assert hp_threshold_status(15, 20) == "healthy"

    def test_bloodied(self):
        assert hp_threshold_status(10, 20) == "bloodied"
        assert hp_threshold_status(6, 20) == "bloodied"

    def test_critical(self):
        assert hp_threshold_status(5, 20) == "critical"
        assert hp_threshold_status(1, 20) == "critical"

    def test_fallen(self):
        assert hp_threshold_status(0, 20) == "fallen"

    def test_negative_hp(self):
        assert hp_threshold_status(-5, 20) == "fallen"

    def test_exact_50_percent(self):
        assert hp_threshold_status(10, 20) == "bloodied"

    def test_exact_25_percent(self):
        assert hp_threshold_status(5, 20) == "critical"

    def test_just_above_50(self):
        assert hp_threshold_status(11, 20) == "healthy"


# --- calculate_combat_xp ---


class TestCalculateCombatXp:
    def test_sums_values(self):
        enemies = [{"xp_value": 50}, {"xp_value": 100}, {"xp_value": 200}]
        assert calculate_combat_xp(enemies) == 350

    def test_empty_list(self):
        assert calculate_combat_xp([]) == 0

    def test_missing_xp_value_defaults_zero(self):
        enemies = [{"name": "goblin"}, {"xp_value": 100}]
        assert calculate_combat_xp(enemies) == 100

    def test_single_enemy(self):
        assert calculate_combat_xp([{"xp_value": 200}]) == 200


# --- advancement thresholds ---


class TestAdvancementThresholds:
    def test_three_transitions(self):
        assert ADVANCEMENT_THRESHOLDS["untrained"] == 8
        assert ADVANCEMENT_THRESHOLDS["trained"] == 20
        assert ADVANCEMENT_THRESHOLDS["expert"] == 40

    def test_no_master_threshold(self):
        assert "master" not in ADVANCEMENT_THRESHOLDS


# --- skill capabilities data ---


class TestSkillCapabilitiesData:
    def test_all_20_skills_present(self):
        assert len(SKILL_CAPABILITIES) == 20
        for skill in SKILLS:
            assert skill in SKILL_CAPABILITIES, f"Missing capabilities for {skill}"

    def test_each_skill_has_expert_and_master(self):
        for skill, caps in SKILL_CAPABILITIES.items():
            assert "expert" in caps, f"{skill} missing expert unlock"
            assert "master" in caps, f"{skill} missing master unlock"
            assert len(caps["expert"]) > 0, f"{skill} expert unlock is empty"
            assert len(caps["master"]) > 0, f"{skill} master unlock is empty"


# --- dataclass construction ---


class TestAdvancementResultDataclass:
    def test_construction(self):
        result = AdvancementResult(
            skill="athletics",
            new_use_count=8,
            advanced=True,
            old_tier="untrained",
            new_tier="trained",
            narrative_cue="Your Athletics has improved!",
        )
        assert result.skill == "athletics"
        assert result.advanced is True
        assert result.old_tier == "untrained"
        assert result.new_tier == "trained"

    def test_frozen(self):
        result = AdvancementResult(
            skill="athletics",
            new_use_count=1,
            advanced=False,
            old_tier="untrained",
            new_tier="untrained",
            narrative_cue="",
        )
        with pytest.raises(AttributeError):
            result.advanced = True  # type: ignore[misc]


class TestSkillCapabilitiesDataclass:
    def test_construction(self):
        caps = SkillCapabilities(
            skill="athletics",
            tier="expert",
            expert_unlock="Superhuman feats",
            master_unlock=None,
        )
        assert caps.skill == "athletics"
        assert caps.expert_unlock == "Superhuman feats"
        assert caps.master_unlock is None

    def test_frozen(self):
        caps = SkillCapabilities(
            skill="athletics",
            tier="trained",
            expert_unlock=None,
            master_unlock=None,
        )
        with pytest.raises(AttributeError):
            caps.tier = "expert"  # type: ignore[misc]


# --- record_skill_use ---


class TestRecordSkillUse:
    def test_increments_counter(self):
        result = record_skill_use({}, "athletics", {})
        assert result.new_use_count == 1
        assert result.skill == "athletics"

    def test_increments_existing_counter(self):
        result = record_skill_use({}, "athletics", {"athletics": 5})
        assert result.new_use_count == 6

    def test_no_advancement_below_threshold(self):
        result = record_skill_use({}, "athletics", {"athletics": 6})
        assert result.advanced is False
        assert result.old_tier == "untrained"
        assert result.new_tier == "untrained"
        assert result.new_use_count == 7

    def test_untrained_to_trained_at_8(self):
        result = record_skill_use({}, "athletics", {"athletics": 7})
        assert result.advanced is True
        assert result.old_tier == "untrained"
        assert result.new_tier == "trained"
        assert result.new_use_count == 8
        assert len(result.narrative_cue) > 0

    def test_trained_to_expert_at_20(self):
        result = record_skill_use({"athletics": "trained"}, "athletics", {"athletics": 19})
        assert result.advanced is True
        assert result.old_tier == "trained"
        assert result.new_tier == "expert"
        assert result.new_use_count == 20

    def test_expert_to_master_at_40_with_narrative_moment(self):
        result = record_skill_use(
            {"athletics": "expert"},
            "athletics",
            {"athletics": 39},
            narrative_moment=True,
        )
        assert result.advanced is True
        assert result.old_tier == "expert"
        assert result.new_tier == "master"
        assert result.new_use_count == 40

    def test_expert_to_master_blocked_without_narrative_moment(self):
        result = record_skill_use({"athletics": "expert"}, "athletics", {"athletics": 39})
        assert result.advanced is False
        assert result.old_tier == "expert"
        assert result.new_tier == "expert"
        assert result.new_use_count == 40

    def test_master_stays_master(self):
        result = record_skill_use({"athletics": "master"}, "athletics", {"athletics": 50})
        assert result.advanced is False
        assert result.old_tier == "master"
        assert result.new_tier == "master"
        assert result.new_use_count == 51

    def test_unknown_skill_raises(self):
        with pytest.raises(ValueError, match="Unknown skill"):
            record_skill_use({}, "flying", {})

    def test_does_not_mutate_inputs(self):
        tiers = {"athletics": "trained"}
        counters = {"athletics": 5}
        tiers_copy = dict(tiers)
        counters_copy = dict(counters)
        record_skill_use(tiers, "athletics", counters)
        assert tiers == tiers_copy
        assert counters == counters_copy

    def test_default_tier_is_untrained(self):
        result = record_skill_use({}, "stealth", {})
        assert result.old_tier == "untrained"


# --- check_skill_capabilities ---


class TestCheckSkillCapabilities:
    def test_untrained_returns_no_unlocks(self):
        caps = check_skill_capabilities("athletics", "untrained")
        assert caps.expert_unlock is None
        assert caps.master_unlock is None

    def test_trained_returns_no_unlocks(self):
        caps = check_skill_capabilities("athletics", "trained")
        assert caps.expert_unlock is None
        assert caps.master_unlock is None

    def test_expert_returns_expert_unlock_only(self):
        caps = check_skill_capabilities("athletics", "expert")
        assert caps.expert_unlock is not None
        assert len(caps.expert_unlock) > 0
        assert caps.master_unlock is None

    def test_master_returns_both_unlocks(self):
        caps = check_skill_capabilities("athletics", "master")
        assert caps.expert_unlock is not None
        assert caps.master_unlock is not None
        assert len(caps.master_unlock) > 0

    def test_all_skills_at_expert(self):
        for skill in SKILLS:
            caps = check_skill_capabilities(skill, "expert")
            assert caps.expert_unlock is not None, f"{skill} missing expert unlock"
            assert len(caps.expert_unlock) > 0

    def test_all_skills_at_master(self):
        for skill in SKILLS:
            caps = check_skill_capabilities(skill, "master")
            assert caps.master_unlock is not None, f"{skill} missing master unlock"
            assert len(caps.master_unlock) > 0

    def test_unknown_skill_raises(self):
        with pytest.raises(ValueError, match="Unknown skill"):
            check_skill_capabilities("flying", "trained")

    def test_returns_correct_skill_and_tier(self):
        caps = check_skill_capabilities("stealth", "expert")
        assert caps.skill == "stealth"
        assert caps.tier == "expert"


# --- Resource Pools ---

# Standard attribute modifiers for testing:
# STR 14 → +2, DEX 12 → +1, CON 13 → +1, INT 16 → +3, WIS 14 → +2, CHA 16 → +3
POOL_TEST_MODS = {
    "strength": 2,
    "dexterity": 1,
    "constitution": 1,
    "intelligence": 3,
    "wisdom": 2,
    "charisma": 3,
}


class TestPoolFormula:
    def test_construction(self):
        f = PoolFormula(base=8, attribute="constitution", level_divisor=1)
        assert f.base == 8
        assert f.attribute == "constitution"
        assert f.level_divisor == 1

    def test_frozen(self):
        f = PoolFormula(base=8, attribute="constitution", level_divisor=1)
        with pytest.raises(AttributeError):
            f.base = 10  # type: ignore[misc]


class TestPoolMaximums:
    def test_construction_stamina_only(self):
        p = PoolMaximums(stamina=10, focus=None, pattern="stamina_only")
        assert p.stamina == 10
        assert p.focus is None
        assert p.pattern == "stamina_only"

    def test_construction_focus_only(self):
        p = PoolMaximums(stamina=None, focus=12, pattern="focus_only")
        assert p.stamina is None
        assert p.focus == 12

    def test_frozen(self):
        p = PoolMaximums(stamina=10, focus=None, pattern="stamina_only")
        with pytest.raises(AttributeError):
            p.stamina = 5  # type: ignore[misc]


class TestArchetypeResourceConfig:
    def test_has_18_archetypes(self):
        assert len(ARCHETYPE_RESOURCE_CONFIG) == 18

    def test_all_keys_lowercase(self):
        for key in ARCHETYPE_RESOURCE_CONFIG:
            assert key == key.lower(), f"Key {key!r} is not lowercase"

    def test_warrior_stamina_config(self):
        pattern, stamina, focus = ARCHETYPE_RESOURCE_CONFIG["warrior"]
        assert pattern == "stamina_only"
        assert stamina is not None
        assert stamina.base == 8
        assert stamina.attribute == "constitution"
        assert stamina.level_divisor == 1
        assert focus is None

    def test_mage_focus_config(self):
        pattern, stamina, focus = ARCHETYPE_RESOURCE_CONFIG["mage"]
        assert pattern == "focus_only"
        assert stamina is None
        assert focus is not None
        assert focus.base == 8
        assert focus.attribute == "intelligence"
        assert focus.level_divisor == 1

    def test_druid_focus_primary_config(self):
        pattern, stamina, focus = ARCHETYPE_RESOURCE_CONFIG["druid"]
        assert pattern == "focus_primary"
        assert stamina is not None
        assert stamina.level_divisor == 0  # flat
        assert focus is not None
        assert focus.level_divisor == 1  # grows with level

    def test_bard_split_config(self):
        pattern, stamina, focus = ARCHETYPE_RESOURCE_CONFIG["bard"]
        assert pattern == "split"
        assert stamina is not None
        assert focus is not None

    def test_marshal_present(self):
        assert "marshal" in ARCHETYPE_RESOURCE_CONFIG
        pattern, stamina, focus = ARCHETYPE_RESOURCE_CONFIG["marshal"]
        assert pattern == "split"
        assert stamina is not None
        assert stamina.attribute == "strength"
        assert focus is not None
        assert focus.attribute == "charisma"

    def test_whisper_is_focus_only(self):
        pattern, stamina, focus = ARCHETYPE_RESOURCE_CONFIG["whisper"]
        assert pattern == "focus_only"
        assert stamina is None
        assert focus is not None
        assert focus.base == 6
        assert focus.level_divisor == 2


class TestCalculateMaxPoolsStaminaOnly:
    def test_warrior_level_1(self):
        result = calculate_max_pools("warrior", 1, POOL_TEST_MODS)
        # 8 + CON(1) + 1 = 10
        assert result.stamina == 10
        assert result.focus is None
        assert result.pattern == "stamina_only"

    def test_warrior_level_10(self):
        result = calculate_max_pools("warrior", 10, POOL_TEST_MODS)
        # 8 + CON(1) + 10 = 19
        assert result.stamina == 19

    def test_warrior_level_20(self):
        result = calculate_max_pools("warrior", 20, POOL_TEST_MODS)
        # 8 + CON(1) + 20 = 29
        assert result.stamina == 29

    def test_skirmisher_uses_dex(self):
        result = calculate_max_pools("skirmisher", 1, POOL_TEST_MODS)
        # 8 + DEX(1) + 1 = 10
        assert result.stamina == 10
        assert result.focus is None

    def test_spy_uses_cha(self):
        result = calculate_max_pools("spy", 1, POOL_TEST_MODS)
        # 8 + CHA(3) + 1 = 12
        assert result.stamina == 12
        assert result.focus is None

    def test_guardian_level_1(self):
        result = calculate_max_pools("guardian", 1, POOL_TEST_MODS)
        # 8 + CON(1) + 1 = 10
        assert result.stamina == 10
        assert result.focus is None

    def test_rogue_uses_dex(self):
        result = calculate_max_pools("rogue", 1, POOL_TEST_MODS)
        # 8 + DEX(1) + 1 = 10
        assert result.stamina == 10
        assert result.focus is None


class TestCalculateMaxPoolsFocusOnly:
    def test_mage_level_1(self):
        result = calculate_max_pools("mage", 1, POOL_TEST_MODS)
        # 8 + INT(3) + 1 = 12
        assert result.stamina is None
        assert result.focus == 12
        assert result.pattern == "focus_only"

    def test_mage_level_10(self):
        result = calculate_max_pools("mage", 10, POOL_TEST_MODS)
        # 8 + INT(3) + 10 = 21
        assert result.focus == 21

    def test_mage_level_20(self):
        result = calculate_max_pools("mage", 20, POOL_TEST_MODS)
        # 8 + INT(3) + 20 = 31
        assert result.focus == 31

    def test_artificer_level_1(self):
        result = calculate_max_pools("artificer", 1, POOL_TEST_MODS)
        # 8 + INT(3) + 1 = 12
        assert result.focus == 12
        assert result.stamina is None

    def test_seeker_level_1(self):
        result = calculate_max_pools("seeker", 1, POOL_TEST_MODS)
        # 8 + INT(3) + 1 = 12
        assert result.focus == 12

    def test_whisper_reduced_formula_level_1(self):
        result = calculate_max_pools("whisper", 1, POOL_TEST_MODS)
        # 6 + INT(3) + 1//2 = 6 + 3 + 0 = 9
        assert result.focus == 9
        assert result.stamina is None
        assert result.pattern == "focus_only"

    def test_whisper_level_10(self):
        result = calculate_max_pools("whisper", 10, POOL_TEST_MODS)
        # 6 + INT(3) + 10//2 = 6 + 3 + 5 = 14
        assert result.focus == 14

    def test_whisper_level_20(self):
        result = calculate_max_pools("whisper", 20, POOL_TEST_MODS)
        # 6 + INT(3) + 20//2 = 6 + 3 + 10 = 19
        assert result.focus == 19


class TestCalculateMaxPoolsFocusPrimary:
    def test_druid_level_1(self):
        result = calculate_max_pools("druid", 1, POOL_TEST_MODS)
        # Stamina: 4 + CON(1) = 5 (flat)
        # Focus: 8 + WIS(2) + 1 = 11
        assert result.stamina == 5
        assert result.focus == 11
        assert result.pattern == "focus_primary"

    def test_druid_level_10_stamina_stays_flat(self):
        result = calculate_max_pools("druid", 10, POOL_TEST_MODS)
        # Stamina: 4 + CON(1) = 5 (flat — no level scaling)
        assert result.stamina == 5
        # Focus: 8 + WIS(2) + 10 = 20
        assert result.focus == 20

    def test_cleric_level_1(self):
        result = calculate_max_pools("cleric", 1, POOL_TEST_MODS)
        assert result.stamina == 5
        assert result.focus == 11

    def test_beastcaller_level_1(self):
        result = calculate_max_pools("beastcaller", 1, POOL_TEST_MODS)
        assert result.stamina == 5
        assert result.focus == 11

    def test_warden_higher_flat_stamina(self):
        result = calculate_max_pools("warden", 1, POOL_TEST_MODS)
        # Stamina: 6 + CON(1) = 7 (higher base than other focus-primary)
        assert result.stamina == 7
        assert result.focus == 11

    def test_oracle_level_1(self):
        result = calculate_max_pools("oracle", 1, POOL_TEST_MODS)
        assert result.stamina == 5
        assert result.focus == 11

    def test_paladin_stamina_grows_at_third_rate(self):
        result = calculate_max_pools("paladin", 1, POOL_TEST_MODS)
        # Stamina: 6 + CON(1) + 1//3 = 6 + 1 + 0 = 7
        # Focus: 6 + WIS(2) + 1 = 9
        assert result.stamina == 7
        assert result.focus == 9

    def test_paladin_level_10(self):
        result = calculate_max_pools("paladin", 10, POOL_TEST_MODS)
        # Stamina: 6 + CON(1) + 10//3 = 6 + 1 + 3 = 10
        # Focus: 6 + WIS(2) + 10 = 18
        assert result.stamina == 10
        assert result.focus == 18

    def test_paladin_level_20(self):
        result = calculate_max_pools("paladin", 20, POOL_TEST_MODS)
        # Stamina: 6 + CON(1) + 20//3 = 6 + 1 + 6 = 13
        # Focus: 6 + WIS(2) + 20 = 28
        assert result.stamina == 13
        assert result.focus == 28


class TestCalculateMaxPoolsSplit:
    def test_bard_level_1(self):
        result = calculate_max_pools("bard", 1, POOL_TEST_MODS)
        # Stamina: 5 + CON(1) + 1//2 = 5 + 1 + 0 = 6
        # Focus: 5 + CHA(3) + 1//2 = 5 + 3 + 0 = 8
        assert result.stamina == 6
        assert result.focus == 8
        assert result.pattern == "split"

    def test_bard_level_10(self):
        result = calculate_max_pools("bard", 10, POOL_TEST_MODS)
        # Stamina: 5 + CON(1) + 10//2 = 5 + 1 + 5 = 11
        # Focus: 5 + CHA(3) + 10//2 = 5 + 3 + 5 = 13
        assert result.stamina == 11
        assert result.focus == 13

    def test_bard_level_20(self):
        result = calculate_max_pools("bard", 20, POOL_TEST_MODS)
        # Stamina: 5 + CON(1) + 20//2 = 5 + 1 + 10 = 16
        # Focus: 5 + CHA(3) + 20//2 = 5 + 3 + 10 = 18
        assert result.stamina == 16
        assert result.focus == 18

    def test_diplomat_both_use_cha(self):
        result = calculate_max_pools("diplomat", 1, POOL_TEST_MODS)
        # Stamina: 5 + CHA(3) + 1//2 = 5 + 3 + 0 = 8
        # Focus: 5 + CHA(3) + 1//2 = 5 + 3 + 0 = 8
        assert result.stamina == 8
        assert result.focus == 8

    def test_marshal_mixed_attributes(self):
        result = calculate_max_pools("marshal", 1, POOL_TEST_MODS)
        # Stamina: 6 + STR(2) + 1//2 = 6 + 2 + 0 = 8
        # Focus: 5 + CHA(3) + 1//2 = 5 + 3 + 0 = 8
        assert result.stamina == 8
        assert result.focus == 8

    def test_marshal_level_10(self):
        result = calculate_max_pools("marshal", 10, POOL_TEST_MODS)
        # Stamina: 6 + STR(2) + 10//2 = 6 + 2 + 5 = 13
        # Focus: 5 + CHA(3) + 10//2 = 5 + 3 + 5 = 13
        assert result.stamina == 13
        assert result.focus == 13


class TestCalculateMaxPoolsEdgeCases:
    def test_unknown_archetype_raises(self):
        with pytest.raises(ValueError, match="Unknown archetype"):
            calculate_max_pools("barbarian", 1, POOL_TEST_MODS)

    def test_negative_modifier(self):
        low_mods = {
            "strength": -2,
            "dexterity": -1,
            "constitution": -3,
            "intelligence": -1,
            "wisdom": 0,
            "charisma": -2,
        }
        result = calculate_max_pools("warrior", 1, low_mods)
        # 8 + CON(-3) + 1 = 6
        assert result.stamina == 6

    def test_missing_attribute_defaults_to_zero(self):
        sparse_mods: dict[str, int] = {}
        result = calculate_max_pools("warrior", 1, sparse_mods)
        # 8 + 0 + 1 = 9
        assert result.stamina == 9


class TestCalculateMaxPoolsAllArchetypesL1L20:
    """Parametrized sanity check: every archetype produces valid pools at L1 and L20."""

    @pytest.mark.parametrize("archetype", list(ARCHETYPE_RESOURCE_CONFIG.keys()))
    def test_level_1_pools_are_positive(self, archetype: str):
        result = calculate_max_pools(archetype, 1, POOL_TEST_MODS)
        if result.stamina is not None:
            assert result.stamina > 0, f"{archetype} L1 stamina <= 0"
        if result.focus is not None:
            assert result.focus > 0, f"{archetype} L1 focus <= 0"

    @pytest.mark.parametrize("archetype", list(ARCHETYPE_RESOURCE_CONFIG.keys()))
    def test_level_20_pools_are_positive(self, archetype: str):
        result = calculate_max_pools(archetype, 20, POOL_TEST_MODS)
        if result.stamina is not None:
            assert result.stamina > 0, f"{archetype} L20 stamina <= 0"
        if result.focus is not None:
            assert result.focus > 0, f"{archetype} L20 focus <= 0"

    @pytest.mark.parametrize("archetype", list(ARCHETYPE_RESOURCE_CONFIG.keys()))
    def test_level_20_pools_ge_level_1(self, archetype: str):
        l1 = calculate_max_pools(archetype, 1, POOL_TEST_MODS)
        l20 = calculate_max_pools(archetype, 20, POOL_TEST_MODS)
        if l1.stamina is not None:
            assert l20.stamina is not None
            assert l20.stamina >= l1.stamina, f"{archetype} L20 stamina < L1"
        if l1.focus is not None:
            assert l20.focus is not None
            assert l20.focus >= l1.focus, f"{archetype} L20 focus < L1"


class TestCalculateMaxPoolsE2E:
    """E2E acceptance criteria: Warrior vs Mage pools differ correctly."""

    def test_warrior_vs_mage_level_1(self):
        warrior = calculate_max_pools("warrior", 1, POOL_TEST_MODS)
        mage = calculate_max_pools("mage", 1, POOL_TEST_MODS)

        # Warrior: stamina-only, Mage: focus-only
        assert warrior.stamina is not None and warrior.focus is None
        assert mage.stamina is None and mage.focus is not None

        # Warrior stamina = 10, Mage focus = 12
        assert warrior.stamina == 10
        assert mage.focus == 12

    def test_warrior_vs_mage_level_10(self):
        warrior = calculate_max_pools("warrior", 10, POOL_TEST_MODS)
        mage = calculate_max_pools("mage", 10, POOL_TEST_MODS)

        # Both scale linearly: warrior stamina = 19, mage focus = 21
        assert warrior.stamina == 19
        assert mage.focus == 21

        # Pools still exclusive
        assert warrior.focus is None
        assert mage.stamina is None
