"""Derive patron tiers from canonical divine favor data."""

from typing import Literal

PatronTier = Literal["Acknowledged", "Devoted", "Exalted"]


def get_patron_tier(favor: dict) -> PatronTier | None:
    max_level = favor["max"]
    level = favor["level"]

    if max_level <= 0:
        raise ValueError(f"max must be positive, got {max_level}")
    if level < 0:
        raise ValueError(f"level must be non-negative, got {level}")
    if level > max_level:
        raise ValueError(f"level must not exceed max, got {level}")

    if favor["patron"] == "none":
        return None

    devoted_level = (max_level * 40 + 99) // 100
    exalted_level = (max_level * 75 + 99) // 100

    if level >= exalted_level:
        return "Exalted"
    if level >= devoted_level:
        return "Devoted"
    return "Acknowledged"
