"""Tests for deriving patron tiers from divine favor."""

import inspect

import pytest

from patron_favor import get_patron_tier


def favor(*, patron: str = "kaelen", level: int, max_level: int) -> dict:
    return {
        "patron": patron,
        "level": level,
        "max": max_level,
        "last_whisper_level": 0,
    }


def test_patron_bound_player_starts_acknowledged_at_zero() -> None:
    assert get_patron_tier(favor(level=0, max_level=100)) == "Acknowledged"


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        (39, "Acknowledged"),
        (40, "Devoted"),
        (74, "Devoted"),
        (75, "Exalted"),
        (100, "Exalted"),
    ],
)
def test_max_100_boundaries_belong_to_the_higher_tier(level: int, expected: str) -> None:
    assert get_patron_tier(favor(level=level, max_level=100)) == expected


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        (23, "Acknowledged"),
        (24, "Devoted"),
        (44, "Devoted"),
        (45, "Exalted"),
    ],
)
def test_tier_boundaries_use_each_patrons_maximum(level: int, expected: str) -> None:
    assert get_patron_tier(favor(level=level, max_level=60)) == expected


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        (24, "Acknowledged"),
        (25, "Devoted"),
        (45, "Devoted"),
        (46, "Exalted"),
    ],
)
def test_fractional_tier_boundaries_round_up(level: int, expected: str) -> None:
    assert get_patron_tier(favor(level=level, max_level=61)) == expected


def test_player_without_a_patron_has_no_tier() -> None:
    assert get_patron_tier(favor(patron="none", level=0, max_level=100)) is None


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (favor(level=0, max_level=0), r"max.*0"),
        (favor(level=0, max_level=-1), r"max.*-1"),
        (favor(level=-1, max_level=100), r"level.*-1"),
        (favor(level=101, max_level=100), r"level.*101"),
    ],
)
def test_invalid_favor_raises_with_the_offending_value(row: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        get_patron_tier(row)


def test_tier_resolver_is_a_pure_synchronous_function() -> None:
    assert list(inspect.signature(get_patron_tier).parameters) == ["favor"]
    assert not inspect.iscoroutinefunction(get_patron_tier)
    assert get_patron_tier(favor(level=40, max_level=100)) == "Devoted"
