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
    ARGUMENT_RESISTANCE,
    ARGUMENT_TYPES,
    DISPOSITION_DC_MODIFIER,
    DISPOSITION_SHIFT,
    SocialResult,
    argument_dc_adjust,
    disposition_shift,
    resolve_social_check,
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


class TestResolveSocialCheckTier1:
    """Tier 1 (spec L636-687): dc = base_dc + disposition modifier; success = roll >= dc."""

    def test_disposition_modifier_adds_to_base_dc(self):
        # Same roll_total against the same base_dc: hostile (+6) is harder than friendly (-3).
        vs_hostile = resolve_social_check(disposition="hostile", skill="persuasion", roll_total=15, base_dc=12)
        vs_friendly = resolve_social_check(disposition="friendly", skill="persuasion", roll_total=15, base_dc=12)
        assert vs_hostile.dc == 18 and not vs_hostile.success  # 15 < 18
        assert vs_friendly.dc == 9 and vs_friendly.success  # 15 >= 9
        assert vs_hostile.margin == -3
        assert vs_friendly.margin == 6

    def test_returns_disposition_shift_and_clamped_new_disposition(self):
        # Persuasion success by 6 -> +1; neutral shifts to friendly.
        r = resolve_social_check(disposition="neutral", skill="persuasion", roll_total=18, base_dc=12)
        assert r.disposition_shift == 1
        assert r.new_disposition == "friendly"

    def test_new_disposition_clamps_at_ladder_ends(self):
        # A big failure against an already-hostile NPC cannot fall off the ladder.
        r = resolve_social_check(disposition="hostile", skill="intimidation", roll_total=1, base_dc=14)
        assert r.disposition_shift < 0
        assert r.new_disposition == "hostile"

    def test_dramatic_routes_through_m45_ssot(self):
        # Razor-thin margin (<=1) is dramatic via dramatic.py, labeled razor_thin.
        thin = resolve_social_check(disposition="neutral", skill="persuasion", roll_total=12, base_dc=12)
        assert thin.dramatic and thin.context == "razor_thin"
        # A comfortable, low-stakes win is not dramatic.
        calm = resolve_social_check(disposition="friendly", skill="persuasion", roll_total=25, base_dc=10)
        assert not calm.dramatic

    def test_high_stakes_is_dramatic_even_on_a_wide_margin(self):
        r = resolve_social_check(disposition="neutral", skill="persuasion", roll_total=25, base_dc=10, stakes="high")
        assert r.dramatic and r.context == "high_stakes_social"

    def test_every_result_carries_a_narration_cue(self):
        for total in (30, 18, 12, 9, 2):
            r = resolve_social_check(disposition="neutral", skill="persuasion", roll_total=total, base_dc=12)
            assert isinstance(r, SocialResult)
            assert r.narrative_cue  # non-empty

    def test_off_ladder_disposition_fails_loud(self):
        with pytest.raises(ValueError, match="wary"):
            resolve_social_check(disposition="wary", skill="persuasion", roll_total=10, base_dc=10)


class TestArgumentDcAdjust:
    """Tier-3 argument categories vs NPC resistance personality (spec L768-791)."""

    def test_no_argument_is_neutral(self):
        # A Tier-1 simple check passes argument_type=None -> no adjustment.
        assert argument_dc_adjust(None, ()) == 0
        assert argument_dc_adjust(None, ("pragmatic",)) == 0

    def test_vulnerable_argument_lowers_dc(self):
        # Pragmatic NPC is vulnerable to self-interest -> easier (negative adjust).
        assert argument_dc_adjust("self_interest", ("pragmatic",)) < 0

    def test_resistant_argument_raises_dc(self):
        # Pragmatic NPC resists emotional appeals -> harder (positive adjust).
        assert argument_dc_adjust("emotion", ("pragmatic",)) > 0

    def test_unrelated_argument_is_neutral(self):
        # Cowardly profile neither favors nor resists evidence -> no change.
        assert argument_dc_adjust("evidence", ("cowardly",)) == 0

    def test_conflicting_tags_net_out(self):
        # An NPC both pragmatic (resists emotion) and emotional (vulnerable to emotion).
        assert argument_dc_adjust("emotion", ("pragmatic", "emotional")) == 0

    def test_resistance_map_uses_only_canonical_argument_types(self):
        for profile in ARGUMENT_RESISTANCE.values():
            for arg in (*profile["vulnerable"], *profile["resistant"]):
                assert arg in ARGUMENT_TYPES

    def test_unknown_argument_type_fails_loud(self):
        with pytest.raises(ValueError, match="flattery"):
            argument_dc_adjust("flattery", ("pragmatic",))

    def test_unknown_personality_tag_fails_loud(self):
        with pytest.raises(ValueError, match="grumpy"):
            argument_dc_adjust("reason", ("grumpy",))


class TestResolveSocialCheckTier3:
    def test_matching_argument_makes_the_check_easier(self):
        # Same roll vs same NPC: a vulnerable argument succeeds where a bare check would not.
        plain = resolve_social_check(disposition="neutral", skill="persuasion", roll_total=14, base_dc=15)
        favored = resolve_social_check(
            disposition="neutral",
            skill="persuasion",
            roll_total=14,
            base_dc=15,
            argument_type="self_interest",
            resistance_tags=("greedy",),
        )
        assert not plain.success
        assert favored.dc < plain.dc
        assert favored.success

    def test_resistant_argument_makes_the_check_harder(self):
        r = resolve_social_check(
            disposition="neutral",
            skill="persuasion",
            roll_total=16,
            base_dc=15,
            argument_type="emotion",
            resistance_tags=("pragmatic",),
        )
        assert r.dc > 15
