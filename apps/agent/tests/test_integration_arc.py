import json

from session_data import SessionData
from tool_support import LOCATION_CORRUPTION


def _make_session(**kwargs: object) -> SessionData:
    sd = SessionData(player_id="player_1", location_id="accord_market_square")
    for key, value in kwargs.items():
        setattr(sd, key, value)
    return sd


class TestNavigationPath:
    def test_session_path_locations_exist(self):
        from pathlib import Path

        locations = json.loads((Path(__file__).parent.parent.parent.parent / "content" / "locations.json").read_text())
        location_ids = {loc["id"] for loc in locations}

        path = [
            "accord_market_square",
            "accord_guild_hall",
            "greyvale_south_road",
            "millhaven",
            "greyvale_wilderness_north",
            "hollow_incursion_site",
            "greyvale_ruins_exterior",
            "greyvale_ruins_entrance",
        ]
        for loc_id in path:
            assert loc_id in location_ids, f"Path location '{loc_id}' not found in content"

    def test_corruption_levels_on_path(self):
        assert LOCATION_CORRUPTION.get("accord_market_square", 0) == 0
        assert LOCATION_CORRUPTION.get("millhaven", 0) == 0
        assert LOCATION_CORRUPTION.get("greyvale_wilderness_north", 0) == 1
        assert LOCATION_CORRUPTION.get("hollow_incursion_site", 0) == 2
        assert LOCATION_CORRUPTION.get("greyvale_ruins_entrance", 0) == 2
        assert LOCATION_CORRUPTION.get("greyvale_ruins_inner", 0) == 3
