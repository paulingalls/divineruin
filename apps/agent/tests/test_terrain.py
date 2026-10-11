import pytest

from terrain import TerrainType, is_earth_or_stone, is_natural, region_type, resonance_base

EXPECTED = {
    "ancient_forest": (0.1, True, True, "wilderness"),
    "forest": (0.2, True, True, "wilderness"),
    "grassland": (0.2, True, True, "wilderness"),
    "mountain": (0.2, True, True, "wilderness"),
    "coast": (0.2, True, False, "wilderness"),
    "wetland": (0.2, True, False, "wilderness"),
    "underground": (0.2, True, True, "dungeon"),
    "farmland": (0.3, True, True, "wilderness"),
    "village": (0.4, False, False, "city"),
    "city": (0.5, False, False, "city"),
}


def test_decision_130():
    assert {value.value for value in TerrainType} == set(EXPECTED)
    for value, expected in EXPECTED.items():
        assert (
            tuple(accessor(value) for accessor in (resonance_base, is_natural, is_earth_or_stone, region_type))
            == expected
        )


@pytest.mark.parametrize("accessor", [resonance_base, is_natural, is_earth_or_stone])
def test_unknown_scalar_terrain(accessor):
    with pytest.raises(ValueError, match="unknown_terrain"):
        accessor("unknown_terrain")
