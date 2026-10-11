"""Decision 130 terrain properties, shared by seed validation and runtime mechanics."""

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from region_types import RegionType


class TerrainType(StrEnum):
    ANCIENT_FOREST = "ancient_forest"
    FOREST = "forest"
    GRASSLAND = "grassland"
    MOUNTAIN = "mountain"
    COAST = "coast"
    WETLAND = "wetland"
    UNDERGROUND = "underground"
    FARMLAND = "farmland"
    VILLAGE = "village"
    CITY = "city"


@dataclass(frozen=True)
class TerrainProperties:
    resonance_base: float
    is_natural: bool
    is_earth_or_stone: bool
    region_type: RegionType


TERRAIN_PROPERTIES = MappingProxyType(
    {
        TerrainType.ANCIENT_FOREST: TerrainProperties(0.1, True, True, "wilderness"),
        TerrainType.FOREST: TerrainProperties(0.2, True, True, "wilderness"),
        TerrainType.GRASSLAND: TerrainProperties(0.2, True, True, "wilderness"),
        TerrainType.MOUNTAIN: TerrainProperties(0.2, True, True, "wilderness"),
        TerrainType.COAST: TerrainProperties(0.2, True, False, "wilderness"),
        TerrainType.WETLAND: TerrainProperties(0.2, True, False, "wilderness"),
        TerrainType.UNDERGROUND: TerrainProperties(0.2, True, True, "dungeon"),
        TerrainType.FARMLAND: TerrainProperties(0.3, True, True, "wilderness"),
        TerrainType.VILLAGE: TerrainProperties(0.4, False, False, "city"),
        TerrainType.CITY: TerrainProperties(0.5, False, False, "city"),
    }
)


def properties(value: str) -> TerrainProperties:
    try:
        return TERRAIN_PROPERTIES[TerrainType(value)]
    except ValueError:
        raise ValueError(f"Unknown terrain {value!r}") from None


def resonance_base(value: str) -> float:
    return properties(value).resonance_base


def is_natural(value: str) -> bool:
    return properties(value).is_natural


def is_earth_or_stone(value: str) -> bool:
    return properties(value).is_earth_or_stone


def region_type(value: str) -> RegionType:
    return properties(value).region_type
