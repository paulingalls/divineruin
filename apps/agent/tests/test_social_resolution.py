"""Tests for social_resolution — the pure 3-tier social-encounter engine (M4.6a / story-001).

resolve_social_check / resolve_contested_social turn an NPC disposition plus a caller-
supplied skill-check total into a social outcome (success, margin, dramatic verdict,
disposition shift, narration cue). Zero IO, zero RNG — the caller rolls. Spec:
docs/game_mechanics/game_mechanics_combat.md §Social Encounter Resolution (L619-844).
"""

from itertools import pairwise

import pytest

from role_archetypes import DISPOSITIONS
from social_resolution import DISPOSITION_DC_MODIFIER, social_dc_modifier


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
