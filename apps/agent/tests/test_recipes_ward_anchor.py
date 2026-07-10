"""Content-code pin for veil-ward anchor recipes — M24 story-007.

Pins the relationship between:
- content/recipes.json: veil_ward_anchor_small and veil_ward_anchor_large
- content/items.json: their tool item definitions
- apps/agent/veil_ward.py: WARD_SOURCES["artificer"] duration constant, and the
  VEIL_ANCHORS item->ward table (story-012)

These halves must not drift apart. Load strictly — fail loud on a missing file
rather than skip (pytest.skip would let a moved or deleted file pass silently).
"""

import json
from pathlib import Path

from veil_ward import ANCHOR_SOURCE, VEIL_ANCHORS, WARD_SOURCES, WardDurationKind

CONTENT_DIR = Path(__file__).parent.parent.parent.parent / "content"


def _load_content(filename: str) -> list[dict]:
    """Load a content JSON file strictly — fail loud (not skip) if it's missing or moved."""
    return json.loads((CONTENT_DIR / filename).read_text())


def _find_by_id(entities: list[dict], entity_id: str, source: str) -> dict:
    """Return the entity with the given id, or fail loud naming where we looked."""
    for entity in entities:
        if entity.get("id") == entity_id:
            return entity
    raise AssertionError(f"'{entity_id}' not found in {source}")


def test_veil_ward_anchor_small_recipe_outputs_self_and_is_tool():
    """veil_ward_anchor_small recipe must output veil_ward_anchor_small item (tier-3 tool)."""
    anchor_recipe = _find_by_id(_load_content("recipes.json"), "veil_ward_anchor_small", "recipes.json")
    assert anchor_recipe["output_item"] == "veil_ward_anchor_small", (
        f"Recipe 'veil_ward_anchor_small' outputs '{anchor_recipe['output_item']}' instead of 'veil_ward_anchor_small'"
    )

    anchor_item = _find_by_id(_load_content("items.json"), "veil_ward_anchor_small", "items.json")
    assert anchor_item["type"] == "tool", (
        f"Item 'veil_ward_anchor_small' has type '{anchor_item['type']}' instead of 'tool'"
    )


def test_veil_ward_anchor_large_recipe_outputs_self():
    """veil_ward_anchor_large recipe must output veil_ward_anchor_large item (tier-4 tool)."""
    anchor_recipe = _find_by_id(_load_content("recipes.json"), "veil_ward_anchor_large", "recipes.json")
    assert anchor_recipe["output_item"] == "veil_ward_anchor_large", (
        f"Recipe 'veil_ward_anchor_large' outputs '{anchor_recipe['output_item']}' instead of 'veil_ward_anchor_large'"
    )

    anchor_item = _find_by_id(_load_content("items.json"), "veil_ward_anchor_large", "items.json")
    assert anchor_item["type"] == "tool", (
        f"Item 'veil_ward_anchor_large' has type '{anchor_item['type']}' instead of 'tool'"
    )


def test_artificer_ward_source_duration_matches_anchor_small():
    """Pin the content-code join: the anchor item's advertised duration matches the code constant.

    Each half is guarded by a different assertion, and it is worth being precise about which:
    the ``seconds == 3600`` pin below catches a drifted CONSTANT, while the derived-substring
    assertion catches drifted ITEM TEXT (retitle the effect "2 hours" and it goes red, because the
    expected string is computed from the constant rather than hardcoded). Neither half can move
    without the other following.
    """
    artificer_source = WARD_SOURCES["artificer"]

    assert artificer_source.duration.kind == WardDurationKind.REAL_TIME, (
        f"artificer WardSource duration kind is '{artificer_source.duration.kind}' instead of REAL_TIME"
    )
    assert artificer_source.duration.seconds == 3600, (
        f"artificer WardSource duration is {artificer_source.duration.seconds}s instead of 3600s (1 hour)"
    )

    # The expected string is DERIVED from the constant, not hardcoded, so an edit to the item's
    # effect text alone turns this red. (A drifted constant is caught by the pin above, first.)
    anchor_item = _find_by_id(_load_content("items.json"), "veil_ward_anchor_small", "items.json")
    effect_text = " ".join(effect.get("description", "") for effect in anchor_item.get("effects", []))
    hours = artificer_source.duration.seconds // 3600
    assert f"{hours} hour" in effect_text, (
        f"Small anchor item effect '{effect_text}' does not advertise the "
        f"{hours}h duration the artificer WardSource constant ({artificer_source.duration.seconds}s) encodes"
    )

    # An anchor is placed, never willed into being — story-005's gate depends on this being False.
    assert artificer_source.tool_raisable is False, (
        f"artificer WardSource tool_raisable is {artificer_source.tool_raisable} instead of False"
    )


def test_veil_anchors_table_matches_the_item_prose():
    """Pin the VEIL_ANCHORS code table to what content/items.json promises the player (story-012).

    The item's "consumed on use" / "not consumed" and "1 hour" / "Permanent" contracts live ONLY in
    free-text effects[].description — there is no consumable field, no duration field. VEIL_ANCHORS
    is where that prose becomes data, so this is the join that keeps them honest. Retitle the large
    anchor "Lasts a week" and it goes red; flip its `consumed` and it goes red.
    """
    items = _load_content("items.json")

    small_item = _find_by_id(items, "veil_ward_anchor_small", "items.json")
    small_text = " ".join(e.get("description", "") for e in small_item.get("effects", []))
    small = VEIL_ANCHORS["veil_ward_anchor_small"]
    assert small.duration.kind == WardDurationKind.REAL_TIME
    assert f"{small.duration.seconds // 3600} hour" in small_text
    assert small.consumed is True and "consumed on use" in small_text.lower()
    assert small.dismissible is True

    large_item = _find_by_id(items, "veil_ward_anchor_large", "items.json")
    large_text = " ".join(e.get("description", "") for e in large_item.get("effects", []))
    large = VEIL_ANCHORS["veil_ward_anchor_large"]
    assert large.duration.kind == WardDurationKind.PERMANENT, (
        "the large anchor's ward must be PERMANENT — its duration cannot come from the artificer "
        "WardSource row, whose REAL_TIME 3600s is the SMALL anchor's hour"
    )
    assert "permanent" in large_text.lower()
    assert large.consumed is False and "not consumed" in large_text.lower()
    # dismiss_ward's DELETE carries `AND dismissible`; False is what makes the row unremovable.
    assert large.dismissible is False


def test_both_anchors_are_sourced_to_the_artificer_who_crafted_them():
    """A crafted object names its maker. The large anchor shares the Sacred site's permanent
    REPRESENTATION (expires_at NULL, undismissible) but not its provenance."""
    assert ANCHOR_SOURCE == "artificer"
    assert ANCHOR_SOURCE in WARD_SOURCES
    assert set(VEIL_ANCHORS) == {"veil_ward_anchor_small", "veil_ward_anchor_large"}
