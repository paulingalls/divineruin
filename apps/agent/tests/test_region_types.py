"""Tests for region type constants."""

from typing import get_args

from region_types import REGION_CITY, REGION_DUNGEON, REGION_WILDERNESS, RegionType


class TestRegionTypeConstants:
    def test_city_value(self):
        assert REGION_CITY == "city"

    def test_wilderness_value(self):
        assert REGION_WILDERNESS == "wilderness"

    def test_dungeon_value(self):
        assert REGION_DUNGEON == "dungeon"

    def test_literal_covers_all_constants(self):
        literal_values = set(get_args(RegionType))
        constants = {REGION_CITY, REGION_WILDERNESS, REGION_DUNGEON}
        assert literal_values == constants
