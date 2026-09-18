"""Derive patron tiers from canonical divine favor data."""

from typing import Literal

PatronTier = Literal["Acknowledged", "Devoted", "Exalted"]

_DEVOTED_PERCENT = 40
_EXALTED_PERCENT = 75


def get_patron_tier(favor: dict) -> PatronTier | None:
    """The tier a ``divine_favor`` row sits in right now — derived on read, never stored.

    Thresholds are fractions of the patron's OWN ``max`` rather than of a fixed 0-100 scale:
    ``max`` is already the per-patron denominator the favor bar reads. A fractional boundary
    rounds UP, so a tier is never admitted early.

    ``None`` means the player has no patron — a domain answer, not an error. An unusable row
    (non-positive ``max``, a ``level`` outside 0..max) raises rather than clamping, so a corrupt
    favor row can never read as a tier.
    """
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

    devoted_level = (max_level * _DEVOTED_PERCENT + 99) // 100
    exalted_level = (max_level * _EXALTED_PERCENT + 99) // 100

    if level >= exalted_level:
        return "Exalted"
    if level >= devoted_level:
        return "Devoted"
    return "Acknowledged"
