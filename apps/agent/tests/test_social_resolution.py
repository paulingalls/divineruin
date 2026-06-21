"""Tests for social_resolution — the pure 3-tier social-encounter engine (M4.6a / story-001).

resolve_social_check / resolve_contested_social turn an NPC disposition plus a caller-
supplied skill-check total into a social outcome (success, margin, dramatic verdict,
disposition shift, narration cue). Zero IO, zero RNG — the caller rolls. Spec:
docs/game_mechanics/game_mechanics_combat.md §Social Encounter Resolution (L619-844).
"""

from itertools import pairwise

import pytest

from role_archetypes import DISPOSITIONS
from social_resolution import (
    DISPOSITION_DC_MODIFIER,
    DISPOSITION_SHIFT,
    disposition_shift,
    social_dc_modifier,
)


class TestSocialDcModifier:
    def test_every_tier_maps_to_spec_value(self):
        # Spec L668: hostile +6, unfriendly +3, neutral 0, friendly -3, trusted -6.
        assert social_dc_modifier("hostile") == 6
        assert social_dc_modifier("unfriendly") == 3
        assert social_dc_modifier("neutral") == 0
        assert social_dc_modifier("friendly") == -3
        assert social_dc_modifier("trusted") == -6

    def test_modifier_decreases_monotonically_up_the_ladder(self):
        # Friendlier disposition is always easier (a strictly smaller DC modifier).
        mods = [social_dc_modifier(tier) for tier in DISPOSITIONS]
        assert mods == sorted(mods, reverse=True)
        assert all(a > b for a, b in pairwise(mods))

    def test_table_covers_exactly_the_canonical_ladder(self):
        assert set(DISPOSITION_DC_MODIFIER) == set(DISPOSITIONS)

    def test_off_ladder_disposition_fails_loud(self):
        with pytest.raises(ValueError, match="wary"):
            social_dc_modifier("wary")


class TestDispositionShift:
    """Spec L678-685: shift depends on skill and outcome band (margin = roll_total - dc)."""

    def test_persuasion_success_bands(self):
        assert disposition_shift("persuasion", 12) == 2  # success by 10+
        assert disposition_shift("persuasion", 6) == 1  # success by 5+
        assert disposition_shift("persuasion", 0) == 0  # bare success (0-4)

    def test_persuasion_failure_bands(self):
        assert disposition_shift("persuasion", -3) == 0  # failure by 1-4
        assert disposition_shift("persuasion", -7) == -1  # failure by 5+
        assert disposition_shift("persuasion", -12) == -2  # failure by 10+

    def test_deception_caps_success_at_plus_one(self):
        # Deception never wins more than +1 even on a blowout (they believe, no admiration).
        assert disposition_shift("deception", 15) == 1
        assert disposition_shift("deception", 6) == 1
        assert disposition_shift("deception", -7) == -1

    def test_intimidation_double_edge_penalizes_even_on_success(self):
        # Spec L680-685: intimidation's bare success and any failure damage the relationship.
        assert disposition_shift("intimidation", 12) == 1  # respectful fear
        assert disposition_shift("intimidation", 6) == 0  # compliance without warmth
        assert disposition_shift("intimidation", 1) == -1  # resentful compliance
        assert disposition_shift("intimidation", -3) == -1  # offended
        assert disposition_shift("intimidation", -7) == -2  # hostile now

    def test_band_boundaries_are_inclusive(self):
        # Exactly +10 / +5 / 0 / -5 / -10 land in the higher-magnitude band.
        assert disposition_shift("persuasion", 10) == 2
        assert disposition_shift("persuasion", 5) == 1
        assert disposition_shift("persuasion", -5) == -1
        assert disposition_shift("persuasion", -10) == -2

    def test_table_covers_the_three_social_skills(self):
        assert set(DISPOSITION_SHIFT) == {"persuasion", "deception", "intimidation"}

    def test_unknown_skill_fails_loud(self):
        with pytest.raises(ValueError, match="athletics"):
            disposition_shift("athletics", 5)
