"""The starter tag is one authority for character creation and tier-4 resurrection; retagging must not leave a stale literal."""

import creation_rules
from resurrection import resolve_resurrection_anchor
from starter_zone import STARTER_ZONE_ID, STARTER_ZONE_TAG, get_starter_zone_id


def _tier4_locations(starter_id: str) -> dict[str, dict]:
    """A location map that forces resolution down to tier 4: the death site has no cleared
    battlefield, no same-region settlement, and the player carries no last-rested settlement."""
    return {
        "wild_r3": {"region": "r3", "danger_level": 3},
        starter_id: {
            "region": "r9",
            "settlement_tier": "city",
            "danger_level": 0,
            "tags": [STARTER_ZONE_TAG],
        },
    }


class TestStarterZoneSSOT:
    def test_tier4_follows_the_tag_to_a_retagged_zone(self):
        # Retag a DIFFERENT location as the starter zone (NOT the literal fallback id), with the
        # literal nowhere tagged. Tier-4 must return the newly-tagged zone, proving it follows the
        # SSOT tag and not a hardcoded literal. Fails if a stale hardcoded fallback is used.
        retagged = "frontier_haven"
        assert retagged != STARTER_ZONE_ID
        locations = _tier4_locations(retagged)
        anchor = resolve_resurrection_anchor("wild_r3", locations, {}, combat_cleared=False)
        assert anchor == retagged

    def test_tier4_falls_back_to_literal_only_when_nothing_tagged(self):
        locations = {"wild_r3": {"region": "r3", "danger_level": 3}}
        anchor = resolve_resurrection_anchor("wild_r3", locations, {}, combat_cleared=False)
        assert anchor == STARTER_ZONE_ID

    def test_helper_returns_tagged_zone(self):
        assert get_starter_zone_id(_tier4_locations("frontier_haven")) == "frontier_haven"

    def test_helper_falls_back_when_untagged(self):
        assert get_starter_zone_id({"wild_r3": {"region": "r3"}}) == STARTER_ZONE_ID

    def test_creation_default_start_location_crosslinks_to_ssot(self):
        assert creation_rules.DEFAULT_START_LOCATION == STARTER_ZONE_ID
