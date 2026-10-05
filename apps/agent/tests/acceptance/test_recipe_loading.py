"""Use real seeded rows so the Python parser sees the content stored by the other language."""

from __future__ import annotations

import json
from pathlib import Path

import recipes

_CONTENT_RECIPES = Path(__file__).parents[4] / "content" / "recipes.json"


def _seeded_recipe_ids() -> list[str]:
    raw = json.loads(_CONTENT_RECIPES.read_text())
    rows = raw if isinstance(raw, list) else raw.get("recipes", raw)
    return [r["id"] for r in rows]


async def test_list_recipes_loads_all_seeded(reset_db_pool: str) -> None:
    expected_ids = _seeded_recipe_ids()

    loaded = await recipes.list_recipes()

    assert len(loaded) == len(expected_ids)
    assert {r["id"] for r in loaded} == set(expected_ids)
    # parse_recipe_row ran on real seeded content for every row (no ValueError),
    # so the full 16-field shape is present.
    sample = loaded[0]
    assert set(sample) == {
        "id",
        "name",
        "category",
        "tier",
        "materials",
        "optional_materials",
        "tainted_materials",
        "workspace_required",
        "crafting_dc",
        "time",
        "async_cycles",
        "output_item",
        "output_quantity",
        "study_cost",
        "discovery_sources",
        "narration_cues",
    }


async def test_get_recipe_loads_a_known_recipe(reset_db_pool: str) -> None:
    known_id = _seeded_recipe_ids()[0]

    recipe = await recipes.get_recipe(known_id)
    assert recipe is not None
    assert recipe["id"] == known_id
    assert recipe["category"] in {"weapon", "armor", "consumable", "tool", "enchantment", "ammunition"}

    assert await recipes.get_recipe("no_such_recipe_xyz") is None
