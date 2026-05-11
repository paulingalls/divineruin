"""Tests for level progression table and level-up reward aggregation."""

import pytest

from leveling import (
    LEVEL_PROGRESSION,
    LevelProgression,
    LevelUpRewards,
    get_level_up_rewards,
    get_milestone_narration,
)
from rules_engine import proficiency_bonus


class TestLevelProgressionTable:
    def test_all_20_levels_present(self) -> None:
        assert set(LEVEL_PROGRESSION.keys()) == set(range(1, 21))

    def test_proficiency_matches_rules_engine(self) -> None:
        for level in range(1, 21):
            entry = LEVEL_PROGRESSION[level]
            expected = proficiency_bonus(level)
            assert entry.proficiency_bonus == expected, (
                f"L{level}: progression says +{entry.proficiency_bonus}, rules_engine says +{expected}"
            )

    def test_attribute_points_at_correct_levels(self) -> None:
        for level in range(1, 21):
            entry = LEVEL_PROGRESSION[level]
            if level in {4, 8, 12, 16, 20}:
                assert entry.attribute_points == 2, f"L{level} should grant 2 attribute points"
            else:
                assert entry.attribute_points == 0, f"L{level} should grant 0 attribute points"

    def test_total_attribute_points_is_10(self) -> None:
        total = sum(LEVEL_PROGRESSION[lvl].attribute_points for lvl in range(1, 21))
        assert total == 10

    def test_specialization_fork_only_at_l5(self) -> None:
        for level in range(1, 21):
            entry = LEVEL_PROGRESSION[level]
            if level == 5:
                assert entry.specialization_fork is True
            else:
                assert entry.specialization_fork is False, f"L{level} should not have specialization fork"

    def test_milestone_levels_have_descriptions(self) -> None:
        milestone_levels = {5, 10, 15, 20}
        for level in milestone_levels:
            entry = LEVEL_PROGRESSION[level]
            assert entry.milestone_type is not None, f"L{level} should have a milestone type"
            assert entry.milestone_description is not None, f"L{level} should have a milestone description"
            assert len(entry.milestone_description) > 0, f"L{level} description should be non-empty"

    def test_entries_are_frozen(self) -> None:
        entry = LEVEL_PROGRESSION[1]
        assert isinstance(entry, LevelProgression)
        with pytest.raises(AttributeError):
            entry.level = 99  # type: ignore[misc]


class TestGetLevelUpRewards:
    def test_single_level_no_milestone(self) -> None:
        rewards = get_level_up_rewards(1, 2)
        assert isinstance(rewards, LevelUpRewards)
        assert rewards.attribute_points == 0
        assert rewards.specialization_fork is False
        assert rewards.milestones == []

    def test_single_level_with_attributes_l3_to_l4(self) -> None:
        rewards = get_level_up_rewards(3, 4)
        assert rewards.attribute_points == 2
        assert rewards.specialization_fork is False

    def test_multi_level_accumulation_l1_to_l8(self) -> None:
        rewards = get_level_up_rewards(1, 8)
        # L4 = 2, L8 = 2 => 4 total
        assert rewards.attribute_points == 4
        # L5 has specialization
        assert rewards.specialization_fork is True

    def test_l1_to_l20_gives_10_attribute_points(self) -> None:
        rewards = get_level_up_rewards(1, 20)
        assert rewards.attribute_points == 10
        assert rewards.specialization_fork is True

    def test_proficiency_change_detected(self) -> None:
        # L6 -> L7: proficiency changes from +1 to +2
        rewards = get_level_up_rewards(6, 7)
        assert rewards.proficiency_changed is True
        assert rewards.new_proficiency_bonus == 2

    def test_no_proficiency_change(self) -> None:
        # L1 -> L2: proficiency stays +1
        rewards = get_level_up_rewards(1, 2)
        assert rewards.proficiency_changed is False
        assert rewards.new_proficiency_bonus == 1

    def test_proficiency_change_l13_to_l14(self) -> None:
        rewards = get_level_up_rewards(13, 14)
        assert rewards.proficiency_changed is True
        assert rewards.new_proficiency_bonus == 3

    def test_milestones_collected(self) -> None:
        # L4->L5 should include the specialization milestone
        rewards = get_level_up_rewards(4, 5)
        assert len(rewards.milestones) == 1
        assert rewards.milestones[0]["level"] == 5
        assert rewards.milestones[0]["type"] == "specialization"

    def test_same_level_returns_empty(self) -> None:
        rewards = get_level_up_rewards(5, 5)
        assert rewards.attribute_points == 0
        assert rewards.specialization_fork is False
        assert rewards.milestones == []
        assert rewards.proficiency_changed is False

    def test_from_level_greater_than_to_level_returns_empty(self) -> None:
        rewards = get_level_up_rewards(10, 5)
        assert rewards.attribute_points == 0
        assert rewards.milestones == []


class TestGetMilestoneNarration:
    def test_l10_has_narration(self) -> None:
        narration = get_milestone_narration(10)
        assert narration is not None
        assert len(narration) > 20

    def test_l2_returns_none(self) -> None:
        narration = get_milestone_narration(2)
        assert narration is None

    def test_l5_mentions_specialization_or_path(self) -> None:
        narration = get_milestone_narration(5)
        assert narration is not None
        text = narration.lower()
        assert "specializ" in text or "path" in text or "fork" in text

    def test_l20_mentions_capstone_or_legend(self) -> None:
        narration = get_milestone_narration(20)
        assert narration is not None
        text = narration.lower()
        assert "capstone" in text or "legend" in text or "ultimate" in text


class TestLevelUpE2E:
    def test_l9_to_l10_produces_archetype_milestone(self) -> None:
        rewards = get_level_up_rewards(9, 10)
        assert len(rewards.milestones) >= 1
        milestone = rewards.milestones[0]
        assert milestone["type"] == "archetype_milestone"
        assert len(milestone["description"]) > 20
