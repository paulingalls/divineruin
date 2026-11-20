from copy import deepcopy

import pytest

from combat_spatial import mapping, point, validate_maps, validate_spatial

ZERO = {"x": 0, "y": 0, "z": 0}


@pytest.mark.parametrize("bad", [None, [], {"x": 0}, {**ZERO, "other": 1}])
def test_point_shape_refusal(bad):
    with pytest.raises(ValueError):
        point(bad)


@pytest.mark.parametrize("bad", [None, [], {"": ZERO}, {" ": ZERO}, {1: ZERO}])
def test_mapping_shape_refusal(bad):
    with pytest.raises(ValueError):
        mapping(bad, "positions")


@pytest.mark.parametrize("bad", [None, [], {"center_id": "a"}, {"center_id": "a", "radius_ft": 0, "effect": "silence"}])
def test_zone_shape_refusal(bad):
    with pytest.raises(ValueError):
        validate_maps({"a": ZERO}, {}, {"z": bad}, zone_kinds=("silence",))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s.update(extra=1),
        lambda s: s["speeds"].pop("a"),
        lambda s: s["speeds"].update(unknown=30),
        lambda s: s["speeds"].update(a=-1),
        lambda s: s["positions"].update(unknown=ZERO),
    ],
)
def test_record_shape_refusal(mutate):
    spatial = {"positions": {"a": deepcopy(ZERO)}, "locations": {}, "zones": {}, "speeds": {"a": 30}}
    mutate(spatial)
    with pytest.raises(ValueError):
        validate_spatial(spatial, ["a"])


def test_oversized_integer_coordinate_refusal():
    with pytest.raises(ValueError):
        point({**ZERO, "x": 10**400})


def test_shipped_zone_radii_follow_catalog_owner():
    import json

    from sample_fixtures import CONTENT_ROOT

    templates = json.loads((CONTENT_ROOT / "content/encounter_templates.json").read_text())
    creatures = {row["id"]: row for row in json.loads((CONTENT_ROOT / "content/creatures.json").read_text())}
    assert len(templates) == 19
    for template in templates:
        expected = {}
        for ref in template["enemies"]:
            hollow = creatures[ref["creature_id"]]["hollow"]
            if hollow is not None and hollow["corruption_aura"] > 0:
                expected[ref["id"] + "_corruption_aura"] = {
                    "center_id": ref["id"],
                    "radius_ft": hollow["corruption_aura"],
                }
        assert template["scene_placement"]["zones"] == expected


def test_record_accepts_optional_wall_segments():
    spatial = {"positions": {"wall": ZERO}, "locations": {}, "zones": {}, "speeds": {"wall": 0}}
    assert validate_spatial(spatial, ["wall"]) == spatial
    spatial["structures"] = {}
    assert validate_spatial(spatial, ["wall"]) == spatial
    spatial["structures"]["wall"] = {"start": ZERO, "end": {**ZERO, "x": 10}}
    assert validate_spatial(spatial, ["wall"]) == spatial


@pytest.mark.parametrize(
    ("structures", "error"),
    [
        (None, "nonempty IDs"),
        ({" ": {"start": ZERO, "end": {**ZERO, "x": 10}}}, "nonempty IDs"),
        ({"wall": {"start": ZERO}}, "requires start and end"),
        ({"wall": {"start": ZERO, "end": ZERO, "height": 10}}, "requires start and end"),
        ({"wall": {"start": {"x": 0}, "end": ZERO}}, "point requires"),
        ({"wall": {"start": ZERO, "end": {**ZERO, "extra": 1}}}, "point requires"),
        ({"wall": {"start": ZERO, "end": {**ZERO, "x": True}}}, "finite number"),
        ({"wall": {"start": ZERO, "end": {**ZERO, "x": float("inf")}}}, "finite number"),
        ({"wall": {"start": ZERO, "end": {**ZERO, "z": 10}}}, "horizontal extent"),
    ],
)
def test_record_rejects_malformed_wall_segments(structures, error):
    spatial = {"positions": {"wall": ZERO}, "locations": {}, "zones": {}, "speeds": {"wall": 0}}
    with pytest.raises(ValueError, match=error):
        validate_spatial({**spatial, "structures": structures}, ["wall"])
