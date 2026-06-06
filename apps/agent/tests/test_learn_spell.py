"""learn(kind='spell') acquisition + the level→tier unlock gate (M8 story-005).

Spells add ZERO new @function_tools (ADR 0007): scroll/mentor acquisition rides
the existing learn(kind, id, source) verb via a 'spell' kind dispatched to
spell_tools. A character may not learn a spell above their level allowance —
leveling.MAX_SPELL_TIER_BY_LEVEL (Cantrip/Minor L1, Standard L4, Major L7,
Supreme L13) is the enforced gate (shared with story-006's prepare check).

The literal real-Postgres AC4 (mentor-taught Minor spell -> character_spells with
acquisition_track for npc_teaching, one DB) rides the M8 story-007 capstone
(ADR 0003: real-DB testcontainer fixtures are unreachable from tests/); the unit
tests here cover AC4's behavior with mock seams, consistent with story-004.
"""

import pytest

import leveling


class TestSpellTierGate:
    @pytest.mark.parametrize(
        "tier,min_level",
        [("cantrip", 1), ("minor", 1), ("standard", 4), ("major", 7), ("supreme", 13)],
    )
    def test_unlocked_at_and_above_min_level(self, tier: str, min_level: int):
        assert leveling.is_spell_tier_unlocked(tier, min_level) is True
        assert leveling.is_spell_tier_unlocked(tier, min_level + 1) is True

    @pytest.mark.parametrize(
        "tier,min_level",
        [("standard", 4), ("major", 7), ("supreme", 13)],
    )
    def test_gated_below_min_level(self, tier: str, min_level: int):
        assert leveling.is_spell_tier_unlocked(tier, min_level - 1) is False

    def test_fails_loud_on_unknown_tier(self):
        with pytest.raises(ValueError, match="tier"):
            leveling.is_spell_tier_unlocked("legendary", 20)
