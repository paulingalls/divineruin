"""Tests for skill advancement: thresholds, capabilities, record_skill_use."""

import pytest

from check_resolution import (
    AdvancementResult,
    SkillCapabilities,
    check_skill_capabilities,
    record_skill_use,
)
from rules_engine import (
    ADVANCEMENT_THRESHOLDS,
    SKILL_CAPABILITIES,
    SKILLS,
    SkillTier,
)

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
        tiers: dict[str, SkillTier] = {"athletics": "trained"}
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
