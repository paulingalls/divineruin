"""Tests for the crafting_resolution orchestrator (story-003, M5.3).

The orchestrator joins the pure async_rules.resolve_crafting to the DB-loaded
quality_outcomes tables: it fetches the recipe's category, loads that category's
bonus/flaw row, and threads it into the resolver. resolve_crafting itself is real
(pure); only the two DB accessors are mocked.
"""

import random
from unittest.mock import AsyncMock, patch

import pytest

import crafting_resolution

PLAYER = {
    "level": 3,
    "attributes": {"intelligence": 10},
    "proficiencies": ["arcana"],
}

# arcana mod = +3; dc=11 -> margin = d20 - 8, so a d20 of 20 lands Exceptional.
PARAMETERS = {
    "recipe_id": "iron_sword",
    "result_item_id": "iron_sword",
    "result_item_name": "Iron Sword",
    "required_materials": ["iron_ingot", "leather_strip"],
    "skill": "arcana",
    "dc": 11,
    "workspace_required": "forge",
    "workspace_access": ["field", "forge"],
    "crafting_tier": "expert",
    "tainted_materials": False,
}

WEAPON_TABLES = {
    "id": "weapon",
    "bonus_properties": [{"id": "keen_edge", "name": "Keen Edge", "description": "It hums when it cuts."}],
    "flaws": [{"id": "dull_bite", "name": "Dull Bite", "description": "The edge drags."}],
}


def _seed_for_d20(target: int) -> int:
    for seed in range(2000):
        if random.Random(seed).randint(1, 20) == target:
            return seed
    raise AssertionError(f"no seed for d20={target}")


@pytest.mark.asyncio
async def test_threads_category_tables_and_attaches_bonus():
    activity = {"activity_type": "crafting", "parameters": PARAMETERS}
    with patch("crafting_resolution.get_recipe", new_callable=AsyncMock, return_value={"category": "weapon"}) as gr:
        with patch(
            "crafting_resolution.get_quality_outcomes", new_callable=AsyncMock, return_value=WEAPON_TABLES
        ) as gqo:
            outcome = await crafting_resolution.resolve_crafting_outcome(
                activity, PLAYER, rng=random.Random(_seed_for_d20(20))
            )

    gr.assert_awaited_once_with("iron_sword")
    gqo.assert_awaited_once_with("weapon")
    assert outcome["tier"] == "exceptional"
    assert outcome["bonus_property"] in WEAPON_TABLES["bonus_properties"]
    assert isinstance(outcome, dict)  # asdict'd dataclass


@pytest.mark.asyncio
async def test_absent_recipe_tolerated_no_table_fetch():
    activity = {"activity_type": "crafting", "parameters": PARAMETERS}
    with patch("crafting_resolution.get_recipe", new_callable=AsyncMock, return_value=None):
        with patch("crafting_resolution.get_quality_outcomes", new_callable=AsyncMock) as gqo:
            outcome = await crafting_resolution.resolve_crafting_outcome(
                activity, PLAYER, rng=random.Random(_seed_for_d20(20))
            )

    gqo.assert_not_awaited()  # no recipe -> no category -> no table lookup
    assert outcome["tier"] == "exceptional"
    assert outcome["bonus_property"] is None  # graceful: band resolves, no flavor
