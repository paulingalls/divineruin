"""Content-code pin for veil-ward anchor recipes — M24 story-007.

Pins the relationship between:
- content/recipes.json: veil_ward_anchor_small and veil_ward_anchor_large
- content/items.json: their tool item definitions
- apps/agent/veil_ward.py: WARD_SOURCES["artificer"] duration constant

These halves must not drift apart. Load strictly — fail loud on a missing file
rather than skip (pytest.skip would let a moved or deleted file pass silently).
"""

import json
from pathlib import Path

from veil_ward import WARD_SOURCES, WardDurationKind

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
    """Pin content-code join: artificer WardSource duration matches anchor item's advertised duration.

    The small anchor's item effect advertises '1 hour'; the code constant is 3600s. This test reads
    BOTH halves and ties them together, so a drift on either side (edit the effect text OR the
    constant) turns the test red instead of letting them diverge silently.
    """
    artificer_source = WARD_SOURCES["artificer"]

    assert artificer_source.duration.kind == WardDurationKind.REAL_TIME, (
        f"artificer WardSource duration kind is '{artificer_source.duration.kind}' instead of REAL_TIME"
    )
    assert artificer_source.duration.seconds == 3600, (
        f"artificer WardSource duration is {artificer_source.duration.seconds}s instead of 3600s (1 hour)"
    )

    # The hour count is DERIVED from the constant, not hardcoded: change the constant to 2 hours and
    # this goes red until the item text follows. That is what makes it a join rather than two pins.
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
