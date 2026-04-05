"""Tests for core rules engine: attributes, skills, DC, proficiency."""

import pytest

from rules_engine import (
    DC_TIERS,
    SKILL_TIER_BONUS,
    SKILL_TIER_ORDER,
    SKILLS,
    DcTier,
    SkillTier,
    attribute_modifier,
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
        assert narrative_hint(15, 22, 13) == "succeeded overwhelmingly"
