import json
import re
from pathlib import Path

import travel
from terrain import TerrainType
from world_regions import REGION_IDS

_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_LOCATIONS = _REPO_ROOT / "content" / "locations.json"
_MIGRATION_055 = _REPO_ROOT / "scripts" / "migrations" / "055_travel_state.sql"

_TRAVEL_TAGS = {"road", "travel"}


def _load_locations() -> list[dict]:
    return json.loads(_LOCATIONS.read_text())


def _travel_locations() -> list[dict]:
    out = []
    for loc in _load_locations():
        tags = set(loc.get("tags", []))
        if loc.get("region_type") == "wilderness" or (tags & _TRAVEL_TAGS):
            out.append(loc)
    return out


def test_navigation_preserves_travel_location_values():
    assert {loc["id"]: loc["navigation"] for loc in _load_locations() if "navigation" in loc} == {
        "greyvale_ruins_exterior": "unmarked_wilderness",
        "greyvale_wilderness_north": "dense_forest",
        "greyvale_south_road": "established_road",
        "millhaven": "established_road",
        "thornveld_old_growth_grove": "dense_forest",
        "keldaran_southern_pass": "known_trail",
        "sunward_tidal_shore": "known_trail",
        "sunward_reed_marsh": "unmarked_wilderness",
    }


def test_every_travel_location_has_a_canonical_navigation():
    locations = _travel_locations()
    assert locations, "no travel-reachable locations matched the selector"
    offenders = []
    for loc in locations:
        navigation = loc.get("navigation")
        if navigation not in travel.NAVIGATION_DC:
            offenders.append((loc.get("id"), navigation))
    assert not offenders, (
        f"travel locations with missing/unknown navigation (expected one of {tuple(travel.NAVIGATION_DC)}): {offenders}"
    )


def test_every_travel_location_has_integer_danger_level():
    offenders = [
        (loc.get("id"), loc.get("danger_level"))
        for loc in _travel_locations()
        if not isinstance(loc.get("danger_level"), int)
    ]
    assert not offenders, f"travel locations with missing/non-int danger_level: {offenders}"


# The terrain exemplars the location-authoring guide names as copyable.
_TERRAIN_EXEMPLARS = {
    "thornveld_old_growth_grove": ("ancient_forest", "thornveld"),
    "keldaran_southern_pass": ("mountain", "keldaran_mountains"),
    "sunward_tidal_shore": ("coast", "sunward_coast"),
    "sunward_reed_marsh": ("wetland", "sunward_coast"),
}


def _by_id() -> dict[str, dict]:
    return {loc["id"]: loc for loc in _load_locations()}


def test_catalog_covers_every_terrain():
    assert {loc["terrain"] for loc in _load_locations()} == set(TerrainType)


def test_terrain_exemplars_are_tier1_wilderness_in_known_regions():
    locations = _by_id()
    for loc_id, (terrain, region) in _TERRAIN_EXEMPLARS.items():
        loc = locations[loc_id]
        assert (loc["terrain"], loc["region"], loc["region_type"], loc["tier"]) == (terrain, region, "wilderness", 1)
        assert region in REGION_IDS


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"[.!?]+", text) if s.strip()]


def test_exemplar_descriptions_are_at_most_four_sentences():
    locations = _by_id()
    for loc_id in _TERRAIN_EXEMPLARS:
        loc = locations[loc_id]
        night = loc["conditions"]["time_night"]["description_override"]
        for text in (loc["description"], night):
            assert 1 <= len(_sentences(text)) <= 4, (loc_id, text)


def test_migration_055_exists():
    assert _MIGRATION_055.exists(), "scripts/migrations/055_travel_state.sql is missing"


def test_migration_055_seeds_travel_state_null_idempotently():
    sql = _MIGRATION_055.read_text()
    assert "jsonb_set(data, '{travel_state}', 'null'::jsonb)" in sql, (
        "055 should seed players.data.travel_state to null via jsonb_set"
    )
    assert "where not (data ? 'travel_state')" in sql.lower(), (
        "055 should be idempotent: guard with WHERE NOT (data ? 'travel_state')"
    )
