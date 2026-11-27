"""Deterministic concentration save DC and combat clock arithmetic."""

from caster_state import ConcentrationState

# Floor for the concentration save DC (spec): a small hit still demands at least a DC-10 save.
_MIN_CONCENTRATION_DC = 10


def check_concentration(damage: int) -> int:
    """Return the Constitution save DC to maintain concentration after taking ``damage``.

    DC = max(10, damage // 2) (spec 03_magic.md §M3.4). Fails loud on negative damage —
    damage is always non-negative.
    """
    if damage < 0:
        raise ValueError(f"damage must be non-negative, got {damage}")
    return max(_MIN_CONCENTRATION_DC, damage // 2)


def elapsed_in_round(record: ConcentrationState, round_number: int) -> int:
    assert record.started_round is not None
    return record.elapsed_seconds + 6 * (round_number - record.started_round)
