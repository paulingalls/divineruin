"""Tests for skill-check resolution: resolve_skill_check (tier) + resolve_skill_check_dc (numeric).

Extracted from test_rules_resolution.py (file-size split, debt e69251d2f945) to
keep that file under the 500-line cap.
"""

import random

from test_rules_core import SAMPLE_PLAYER

from check_resolution import resolve_skill_check, resolve_skill_check_dc


class TestResolveSkillCheck:
    def test_success(self):
        # Seed that produces d20=15
        rng = random.Random(42)
        test_roll = rng.randint(1, 20)
        # Reset to same seed for actual call
        rng = random.Random(42)
        result = resolve_skill_check(
            SAMPLE_PLAYER, "athletics", "moderate", rng=rng, ally_present=False, hearing_only=False
        )
        assert result.roll == test_roll
        assert result.skill == "athletics"
        assert result.modifier == 5  # STR +2, trained: prof +1 + tier +2
        assert result.total == test_roll + 5
        assert result.dc == 12  # moderate = 12
        assert result.success == (result.total >= 12 or test_roll == 20)

    def test_nat_20_always_succeeds(self):
        # Find a seed that gives nat 20. Use very_hard (DC 20) to avoid auto-fail for untrained.
        seed = 5
        rng = random.Random(seed)
        result = resolve_skill_check(
            SAMPLE_PLAYER, "persuasion", "very_hard", rng=rng, ally_present=False, hearing_only=False
        )
        assert result.success is True
        assert result.roll == 20
        assert result.narrative_hint == "critical success"

    def test_nat_1_always_fails(self):
        seed = 31
        rng = random.Random(seed)
        result = resolve_skill_check(
            SAMPLE_PLAYER, "athletics", "easy", rng=rng, ally_present=False, hearing_only=False
        )
        assert result.success is False
        assert result.roll == 1
        assert result.narrative_hint == "critical failure"

    def test_proficiency_bonus_applied(self):
        rng = random.Random(42)
        prof_result = resolve_skill_check(
            SAMPLE_PLAYER, "athletics", "moderate", rng=rng, ally_present=False, hearing_only=False
        )
        rng = random.Random(42)
        unprof_result = resolve_skill_check(
            SAMPLE_PLAYER, "persuasion", "moderate", rng=rng, ally_present=False, hearing_only=False
        )
        # athletics: STR+2, trained(prof+1, tier+2) = +5; persuasion: CHA-1, untrained = -1
        assert prof_result.modifier == 5
        assert unprof_result.modifier == -1


class TestResolveSkillCheckDc:
    def test_success_with_numeric_dc(self):
        rng = random.Random(42)
        result = resolve_skill_check_dc(SAMPLE_PLAYER, "athletics", 10, rng=rng, ally_present=False, hearing_only=False)
        assert result.dc == 10
        assert result.skill == "athletics"
        assert result.modifier == 5  # STR +2, trained: prof +1 + tier +2

    def test_failure_with_high_dc(self):
        seed = 0
        rng = random.Random(seed)
        result = resolve_skill_check_dc(SAMPLE_PLAYER, "athletics", 25, rng=rng, ally_present=False, hearing_only=False)
        assert result.success is False
        assert result.dc == 25

    def test_nat_20_always_succeeds(self):
        # Use DC 23 to avoid auto-fail for trained perception (auto-fail at DC 24+)
        seed = 5
        rng = random.Random(seed)
        result = resolve_skill_check_dc(
            SAMPLE_PLAYER, "perception", 23, rng=rng, ally_present=False, hearing_only=False
        )
        assert result.success is True
        assert result.roll == 20

    def test_nat_1_always_fails(self):
        seed = 31
        rng = random.Random(seed)
        result = resolve_skill_check_dc(SAMPLE_PLAYER, "athletics", 1, rng=rng, ally_present=False, hearing_only=False)
        assert result.success is False
        assert result.roll == 1

    def test_uses_numeric_dc_not_tier(self):
        rng = random.Random(42)
        dc_result = resolve_skill_check_dc(
            SAMPLE_PLAYER, "athletics", 14, rng=rng, ally_present=False, hearing_only=False
        )
        assert dc_result.dc == 14
        rng = random.Random(42)
        tier_result = resolve_skill_check(
            SAMPLE_PLAYER, "athletics", "moderate", rng=rng, ally_present=False, hearing_only=False
        )
        assert tier_result.dc == 12  # moderate = 12, not 14
        assert dc_result.dc != tier_result.dc

    def test_proficiency_applied(self):
        rng = random.Random(42)
        result = resolve_skill_check_dc(
            SAMPLE_PLAYER, "perception", 10, rng=rng, ally_present=False, hearing_only=False
        )
        # WIS 11 → +0, trained: prof +1 + tier +2 = +3
        assert result.modifier == 3
