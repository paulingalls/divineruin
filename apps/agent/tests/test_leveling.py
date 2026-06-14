"""Tests for level progression table and level-up reward aggregation."""

import pytest

from dice import roll
from hp_scaling import calculate_max_hp
from leveling import (
    LEVEL_PROGRESSION,
    MIN_LEVEL_BY_ARCHETYPE_TIER,
    SPELL_TIERS,
    LevelProgression,
    LevelUpRewards,
    build_level_up_payload,
    build_level_up_payload_for_archetype,
    cantrip_damage_dice,
    get_level_up_rewards,
    get_milestone_narration,
    is_spell_tier_unlocked,
    min_level_for_tier,
)
from rules_engine import proficiency_bonus

# Expected per-(archetype, tier) unlock level, sourced from game_mechanics_archetypes.md.
# None = the tier is never available to that archetype (e.g. paladin Supreme; the
# half-casters and Whisper have no elective cantrip). Hard-coded (not derived from the
# production table) so a wrong production value is caught, not mirrored.
_FULL_CASTER_FLOORS: dict[str, int | None] = {
    "cantrip": 1,
    "minor": 1,
    "standard": 3,
    "major": 5,
    "supreme": 9,
}
EXPECTED_TIER_FLOORS: dict[str, dict[str, int | None]] = {
    "mage": _FULL_CASTER_FLOORS,
    "artificer": _FULL_CASTER_FLOORS,
    "seeker": _FULL_CASTER_FLOORS,
    "druid": _FULL_CASTER_FLOORS,
    "beastcaller": _FULL_CASTER_FLOORS,
    "warden": _FULL_CASTER_FLOORS,
    "cleric": _FULL_CASTER_FLOORS,
    "oracle": _FULL_CASTER_FLOORS,
    "bard": {"cantrip": 1, "minor": 1, "standard": 3, "major": 5, "supreme": 10},
    "paladin": {"cantrip": None, "minor": 3, "standard": 5, "major": 9, "supreme": None},
    "diplomat": {"cantrip": None, "minor": 3, "standard": 5, "major": 9, "supreme": None},
    "marshal": {"cantrip": None, "minor": 3, "standard": 5, "major": 9, "supreme": None},
    "whisper": {"cantrip": None, "minor": 1, "standard": 4, "major": 7, "supreme": 13},
}


class TestSpellTierGate:
    def test_table_covers_exactly_the_expected_archetypes(self) -> None:
        assert set(MIN_LEVEL_BY_ARCHETYPE_TIER) == set(EXPECTED_TIER_FLOORS)

    def test_spell_tiers_vocab_is_the_five_canonical_tiers(self) -> None:
        assert frozenset({"cantrip", "minor", "standard", "major", "supreme"}) == SPELL_TIERS

    @pytest.mark.parametrize("archetype", sorted(EXPECTED_TIER_FLOORS))
    def test_min_level_for_tier_matches_spec(self, archetype: str) -> None:
        for tier in SPELL_TIERS:
            assert min_level_for_tier(archetype, tier) == EXPECTED_TIER_FLOORS[archetype][tier]

    @pytest.mark.parametrize("archetype", sorted(EXPECTED_TIER_FLOORS))
    def test_unlocked_exactly_at_floor_and_gated_below(self, archetype: str) -> None:
        for tier, floor in EXPECTED_TIER_FLOORS[archetype].items():
            if floor is None:
                # Never-available tier: gated at every level, even the cap.
                assert is_spell_tier_unlocked(archetype, tier, 1) is False
                assert is_spell_tier_unlocked(archetype, tier, 20) is False
            else:
                assert is_spell_tier_unlocked(archetype, tier, floor) is True
                if floor > 1:
                    assert is_spell_tier_unlocked(archetype, tier, floor - 1) is False

    def test_full_casters_unlock_standard_major_supreme_at_3_5_9_not_global_4_7_13(self) -> None:
        # The crux of concern 66fa8bae: the old global gate said 4/7/13.
        assert min_level_for_tier("mage", "standard") == 3
        assert min_level_for_tier("mage", "major") == 5
        assert min_level_for_tier("mage", "supreme") == 9

    def test_half_casters_have_no_supreme_access(self) -> None:
        for archetype in ("paladin", "diplomat", "marshal"):
            assert min_level_for_tier(archetype, "supreme") is None
            assert is_spell_tier_unlocked(archetype, "supreme", 20) is False

    def test_unknown_archetype_fails_loud(self) -> None:
        with pytest.raises(ValueError, match="archetype"):
            is_spell_tier_unlocked("warrior", "minor", 5)
        with pytest.raises(ValueError, match="archetype"):
            min_level_for_tier("rogue", "minor")

    def test_unknown_tier_fails_loud(self) -> None:
        with pytest.raises(ValueError, match="tier"):
            is_spell_tier_unlocked("mage", "legendary", 20)
        with pytest.raises(ValueError, match="tier"):
            min_level_for_tier("mage", "legendary")


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


class TestCantripDamageDice:
    """Numeric cantrip damage scaling — the SSOT cast_spell (story-004) consumes.

    Brackets (03_magic.md L132): 1d6 L1-4, 2d6 L5-10, 3d6 L11-16, 4d6 L17-20.
    """

    def test_bracket_1d6_levels_1_to_4(self) -> None:
        for level in range(1, 5):
            assert cantrip_damage_dice(level) == "1d6", f"L{level} should be 1d6"

    def test_bracket_2d6_levels_5_to_10(self) -> None:
        for level in range(5, 11):
            assert cantrip_damage_dice(level) == "2d6", f"L{level} should be 2d6"

    def test_bracket_3d6_levels_11_to_16(self) -> None:
        for level in range(11, 17):
            assert cantrip_damage_dice(level) == "3d6", f"L{level} should be 3d6"

    def test_bracket_4d6_levels_17_to_20(self) -> None:
        for level in range(17, 21):
            assert cantrip_damage_dice(level) == "4d6", f"L{level} should be 4d6"

    def test_bracket_boundaries(self) -> None:
        # Lower edge stays in the prior bracket; upper edge crosses into the next.
        assert cantrip_damage_dice(4) == "1d6"
        assert cantrip_damage_dice(5) == "2d6"
        assert cantrip_damage_dice(10) == "2d6"
        assert cantrip_damage_dice(11) == "3d6"
        assert cantrip_damage_dice(16) == "3d6"
        assert cantrip_damage_dice(17) == "4d6"

    def test_level_below_1_raises(self) -> None:
        with pytest.raises(ValueError):
            cantrip_damage_dice(0)

    def test_level_above_20_raises(self) -> None:
        with pytest.raises(ValueError):
            cantrip_damage_dice(21)

    def test_every_level_returns_rollable_spec_no_gap(self) -> None:
        # E2E: every level 1-20 yields a dice spec the real roller accepts.
        for level in range(1, 21):
            spec = cantrip_damage_dice(level)
            result = roll(spec)
            assert result.total >= 1, f"L{level} spec {spec!r} rolled non-positive"


class TestArchetypePayload:
    """Archetype-aware level-up payload joins LEVEL_PROGRESSION with ARCHETYPE_HP_CONFIG."""

    def test_includes_base_payload_fields_unchanged(self) -> None:
        rewards = get_level_up_rewards(1, 5)
        base = build_level_up_payload(1, rewards)
        joined = build_level_up_payload_for_archetype(1, rewards, "warrior")
        joined_without_hp = {k: v for k, v in joined.items() if k != "hp_gains"}
        assert joined_without_hp == base

    def test_hp_gain_per_level_warrior_l1_to_l2(self) -> None:
        rewards = get_level_up_rewards(1, 2)
        payload = build_level_up_payload_for_archetype(1, rewards, "warrior")
        expected_delta = calculate_max_hp("warrior", 2, 0) - calculate_max_hp("warrior", 1, 0)
        assert payload["hp_gains"] == [{"level": 2, "hp_gain": expected_delta}]

    def test_hp_gain_per_level_mage_l1_to_l5(self) -> None:
        rewards = get_level_up_rewards(1, 5)
        payload = build_level_up_payload_for_archetype(1, rewards, "mage")
        levels = [entry["level"] for entry in payload["hp_gains"]]
        assert levels == [2, 3, 4, 5]
        total = sum(entry["hp_gain"] for entry in payload["hp_gains"])
        assert total == calculate_max_hp("mage", 5, 0) - calculate_max_hp("mage", 1, 0)

    def test_con_modifier_propagates(self) -> None:
        rewards = get_level_up_rewards(1, 3)
        payload = build_level_up_payload_for_archetype(1, rewards, "paladin", con_mod=2)
        for entry in payload["hp_gains"]:
            lvl = entry["level"]
            expected = calculate_max_hp("paladin", lvl, 2) - calculate_max_hp("paladin", lvl - 1, 2)
            assert entry["hp_gain"] == expected, f"L{lvl} hp_gain mismatch"

    def test_unknown_archetype_raises(self) -> None:
        rewards = get_level_up_rewards(1, 2)
        with pytest.raises(ValueError):
            build_level_up_payload_for_archetype(1, rewards, "invalid_archetype")

    def test_no_levels_gained_returns_empty_hp_gains(self) -> None:
        rewards = get_level_up_rewards(1, 1)
        payload = build_level_up_payload_for_archetype(1, rewards, "warrior")
        assert payload["hp_gains"] == []
