"""Content conformance + migration shape guard for M4.6b travel (story-002).

Pure-parse, no DB (fast lane), mirroring test_social_content.py / test_content_validation.py.
Asserts every travel-reachable location (region_type=wilderness or a road/travel tag) carries
an explicit `terrain` that is a valid travel.NAVIGATION_DC key (travel.py is the SSOT for the
terrain vocabulary) plus a valid integer danger_level, and that migration 055 follows the
established idempotent jsonb_set seed pattern (051-053).

Spec: docs/game_mechanics/game_mechanics_combat.md §Travel and Exploration (L852-969).
"""

import json
from pathlib import Path

import travel

_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_LOCATIONS = _REPO_ROOT / "content" / "locations.json"
_MIGRATION_055 = _REPO_ROOT / "scripts" / "migrations" / "055_travel_state.sql"

# A location is travel-reachable (needs an explicit navigation terrain) when it is a wilderness
# region or carries a road/travel tag. City/dungeon locations are not navigated and omit terrain.
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


# --- Terrain conformance (content vs the travel.NAVIGATION_DC SSOT) ---


def test_travel_locations_exist():
    # Guard the selector itself: if this ever empties, the conformance tests below pass vacuously.
    assert _travel_locations(), "no travel-reachable locations matched the selector"


def test_every_travel_location_has_a_canonical_terrain():
    offenders = []
    for loc in _travel_locations():
        terrain = loc.get("terrain")
        if terrain not in travel.NAVIGATION_DC:
            offenders.append((loc.get("id"), terrain))
    assert not offenders, (
        f"travel locations with missing/unknown terrain (expected one of {tuple(travel.NAVIGATION_DC)}): {offenders}"
    )


def test_every_travel_location_has_integer_danger_level():
    offenders = [
        (loc.get("id"), loc.get("danger_level"))
        for loc in _travel_locations()
        if not isinstance(loc.get("danger_level"), int)
    ]
    assert not offenders, f"travel locations with missing/non-int danger_level: {offenders}"


def test_non_travel_locations_need_no_terrain():
    # The field is optional off the travel surface — assert at least one city location omits it,
    # so the terrain requirement stays scoped to travel-reachable locations (not a blanket field).
    travel_ids = {loc.get("id") for loc in _travel_locations()}
    non_travel = [loc for loc in _load_locations() if loc.get("id") not in travel_ids]
    assert any("terrain" not in loc for loc in non_travel)


# --- Migration 055 shape guard (follows the 051-053 idempotent jsonb_set pattern) ---


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
