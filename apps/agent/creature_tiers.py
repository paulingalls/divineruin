"""Creature tier player-level bands from the game mechanics bestiary."""

TIER_LEVEL_RANGES = {1: (1, 4), 2: (5, 8), 3: (9, 14), 4: (15, 20)}


def player_level_range_for_tier(tier: int) -> tuple[int, int]:
    if tier not in TIER_LEVEL_RANGES:
        raise ValueError(f"unknown creature tier {tier}")
    return TIER_LEVEL_RANGES[tier]


def tier_for_player_level(level: int) -> int:
    matches = [tier for tier, (low, high) in TIER_LEVEL_RANGES.items() if low <= level <= high]
    if len(matches) != 1:
        raise ValueError(f"player level {level} maps to {len(matches)} creature tiers")
    return matches[0]
