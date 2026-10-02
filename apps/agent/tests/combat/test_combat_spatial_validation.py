"""Strict shapes for authored and persisted geometry."""

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
        validate_maps({"a": ZERO}, {}, {"z": bad})


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
    assert len(templates) == 10 and creatures
    expected_count = 0
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
        expected_count += len(expected)
    assert expected_count > 0
