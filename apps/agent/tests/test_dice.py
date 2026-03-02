"""Tests for dice notation parser and roller."""

import random

import pytest

from dice import roll, DiceResult


class TestDiceParser:
    def test_simple_d20(self):
        rng = random.Random(42)
        result = roll("d20", rng=rng)
        assert isinstance(result, DiceResult)
        assert result.notation == "d20"
        assert 1 <= result.total <= 20
        assert len(result.rolls) == 1
        assert result.dropped == []

    def test_multiple_dice(self):
        rng = random.Random(42)
        result = roll("2d6", rng=rng)
        assert len(result.rolls) == 2
        assert all(1 <= r <= 6 for r in result.rolls)
        assert result.total == sum(result.rolls)

    def test_deterministic_with_seed(self):
        r1 = roll("d20", rng=random.Random(99))
        r2 = roll("d20", rng=random.Random(99))
        assert r1.total == r2.total
        assert r1.rolls == r2.rolls

    def test_flat_bonus(self):
        rng = random.Random(42)
        result = roll("1d8+3", rng=rng)
        assert result.total == result.rolls[0] + 3

    def test_flat_penalty(self):
        rng = random.Random(42)
        result = roll("2d6-1", rng=rng)
        assert result.total == sum(result.rolls) - 1

    def test_keep_highest(self):
        rng = random.Random(42)
        result = roll("4d6kh3", rng=rng)
        assert len(result.rolls) == 3
        assert len(result.dropped) == 1
        all_values = sorted(result.rolls + result.dropped)
        assert result.dropped[0] == all_values[0]
        assert result.total == sum(result.rolls)

    def test_keep_lowest(self):
        rng = random.Random(42)
        result = roll("4d6kl1", rng=rng)
        assert len(result.rolls) == 1
        assert len(result.dropped) == 3
        all_values = result.rolls + result.dropped
        assert result.rolls[0] == min(all_values)

    def test_case_insensitive(self):
        rng = random.Random(42)
        result = roll("2D6", rng=rng)
        assert result.notation == "2d6"

    def test_invalid_notation_raises(self):
        with pytest.raises(ValueError, match="Invalid dice notation"):
            roll("not_dice")

    def test_invalid_keep_more_than_rolled(self):
        with pytest.raises(ValueError, match="Cannot keep"):
            roll("2d6kh5")

    def test_zero_dice_raises(self):
        with pytest.raises(ValueError, match="Invalid dice notation"):
            roll("0d6")

    def test_whitespace_trimmed(self):
        rng = random.Random(42)
        result = roll("  d20  ", rng=rng)
        assert result.notation == "d20"
