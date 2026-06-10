"""Tests for the encounter stance resolver (Phase 6 M6.2 / story-005).

resolve_encounter_stance is a pure, deterministic mechanic (golden rule: rules engine =
pure functions): given an encounter's stance_gate, the player's reputation value with the
gated faction, and that faction's reputation_tiers, it returns "allied" or "hostile". The
Ashmark Patrol encounter uses it — allied at >= Thornwatch friendly, hostile below.
"""

import pytest

from encounter_stance import resolve_encounter_stance

# Mirrors a faction's reputation_tiers in content/factions.json (friendly threshold = 5).
_TIERS = {
    "hostile": {"threshold": -10, "effects": []},
    "unfriendly": {"threshold": -5, "effects": []},
    "neutral": {"threshold": 0, "effects": []},
    "friendly": {"threshold": 5, "effects": []},
    "trusted": {"threshold": 15, "effects": []},
    "honored": {"threshold": 25, "effects": []},
}

_GATE = {"faction": "thornwatch", "allied_at_or_above": "friendly"}


class TestResolveEncounterStance:
    def test_allied_at_threshold(self):
        assert resolve_encounter_stance(_GATE, 5, _TIERS) == "allied"

    def test_allied_above_threshold(self):
        assert resolve_encounter_stance(_GATE, 25, _TIERS) == "allied"

    def test_hostile_just_below_threshold(self):
        assert resolve_encounter_stance(_GATE, 4, _TIERS) == "hostile"

    def test_hostile_at_neutral_and_below(self):
        assert resolve_encounter_stance(_GATE, 0, _TIERS) == "hostile"
        assert resolve_encounter_stance(_GATE, -10, _TIERS) == "hostile"

    def test_missing_allied_at_or_above_fails_loud(self):
        with pytest.raises(ValueError, match="allied_at_or_above"):
            resolve_encounter_stance({"faction": "thornwatch"}, 10, _TIERS)

    def test_unknown_tier_fails_loud(self):
        bad = {"faction": "thornwatch", "allied_at_or_above": "legendary"}
        with pytest.raises(ValueError, match="legendary"):
            resolve_encounter_stance(bad, 10, _TIERS)

    def test_tier_missing_threshold_fails_loud(self):
        malformed_tiers = {"friendly": {"effects": []}}
        with pytest.raises(ValueError, match="threshold"):
            resolve_encounter_stance(_GATE, 10, malformed_tiers)
