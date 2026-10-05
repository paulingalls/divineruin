from dataclasses import FrozenInstanceError

import pytest

from death_cost import DeathCost, determine_death_cost


class TestTierMapping:
    @pytest.mark.parametrize(
        "death_count,tier",
        [
            (1, "gentle"),
            (2, "moderate"),
            (3, "severe"),
            (4, "severe"),
            (5, "devastating"),
            (6, "devastating"),
            (9, "devastating"),
        ],
    )
    def test_tier_for_death_count(self, death_count, tier):
        assert determine_death_cost(death_count, level=5).tier == tier

    @pytest.mark.parametrize(
        "death_count,penalty,target",
        [
            (1, 0, "none"),
            (2, 1, "lowest"),
            (3, 1, "primary"),
            (4, 1, "primary"),
            (5, 2, "highest"),
        ],
    )
    def test_attribute_penalty_and_target(self, death_count, penalty, target):
        cost = determine_death_cost(death_count, level=3)
        assert cost.attribute_penalty == penalty
        assert cost.attribute_target == target

    def test_death_count_echoed_on_cost(self):
        assert determine_death_cost(4, level=8).death_count == 4


class TestMaxHpPenalty:
    def test_no_maxhp_penalty_before_death_seven(self):
        cost = determine_death_cost(6, level=10)
        assert cost.maxhp_penalty_per_level == 0
        assert cost.maxhp_penalty_total == 0

    def test_maxhp_penalty_is_minus_one_per_level_at_death_seven(self):
        cost = determine_death_cost(7, level=10)
        assert cost.maxhp_penalty_per_level == 1
        assert cost.maxhp_penalty_total == 10

    def test_maxhp_penalty_scales_with_level(self):
        assert determine_death_cost(8, level=3).maxhp_penalty_total == 3
        assert determine_death_cost(12, level=20).maxhp_penalty_total == 20

    def test_devastating_below_seven_still_has_no_maxhp_penalty(self):
        cost = determine_death_cost(5, level=10)
        assert cost.tier == "devastating"
        assert cost.maxhp_penalty_total == 0


class TestValidation:
    @pytest.mark.parametrize("death_count", [0, -1])
    def test_death_count_must_be_positive(self, death_count):
        with pytest.raises(ValueError):
            determine_death_cost(death_count, level=5)

    @pytest.mark.parametrize("level", [0, -3])
    def test_level_must_be_positive(self, level):
        with pytest.raises(ValueError):
            determine_death_cost(1, level=level)


def test_death_cost_is_frozen():
    cost = determine_death_cost(2, level=5)
    with pytest.raises(FrozenInstanceError):
        cost.tier = "gentle"  # type: ignore[misc]
    assert isinstance(cost, DeathCost)
