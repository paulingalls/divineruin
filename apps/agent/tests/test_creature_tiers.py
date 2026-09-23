import pytest

from creature_tiers import TIER_LEVEL_RANGES, player_level_range_for_tier, tier_for_player_level

EXPECTED = {1: (1, 4), 2: (5, 8), 3: (9, 14), 4: (15, 20)}


@pytest.mark.parametrize("tier,band", EXPECTED.items())
def test_spec_band(tier, band):
    assert TIER_LEVEL_RANGES[tier] == band
    assert player_level_range_for_tier(tier) == band


def test_every_player_level_has_exactly_one_tier():
    for level in range(1, 21):
        matches = [tier for tier, (low, high) in TIER_LEVEL_RANGES.items() if low <= level <= high]
        assert len(matches) == 1, f"level {level}: {matches}"
        assert tier_for_player_level(level) == matches[0]


@pytest.mark.parametrize("level", [0, 21, -1])
def test_outside_player_levels_fail(level):
    with pytest.raises(ValueError):
        tier_for_player_level(level)


@pytest.mark.parametrize("tier", [0, 5])
def test_invalid_tier_fails(tier):
    with pytest.raises(ValueError):
        player_level_range_for_tier(tier)
