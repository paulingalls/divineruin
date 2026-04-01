"""Region type constants and type alias."""

from typing import Literal

REGION_CITY = "city"
REGION_WILDERNESS = "wilderness"
REGION_DUNGEON = "dungeon"

RegionType = Literal["city", "wilderness", "dungeon"]
