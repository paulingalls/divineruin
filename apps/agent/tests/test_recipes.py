"""Tests for the Python recipe accessors (story-005, M5.1).

Mirrors the mocked-pool style of test_db.py: patch db._cache_get / _cache_set /
db.get_pool. The agent reads recipes from the DB (constraint 8508fdb1abc3) the
same way the TS server does (apps/server/src/recipes.ts) — recipe:<id> and
recipes:all cache keys, fail-loud parse via parse_recipe_row.

There is no real-DB pytest harness in the agent suite; these are unit tests with
a mocked pool, exactly like every other db_content_queries accessor.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

import recipes

# A fully-specified recipe row's `data` payload (the 15 non-id Recipe fields;
# id is the row key, passed separately to parse_recipe_row — mirrors TS).
VALID_RECIPE_DATA = {
    "name": "Iron Sword",
    "category": "weapon",
    "tier": "trained",
    "materials": [{"material_id": "iron_ingot", "quantity": 2, "tier_minimum": 1, "substitutable": True}],
    "optional_materials": [{"material_id": "leather_strip", "quantity": 1, "tier_minimum": 1, "substitutable": False}],
    "tainted_materials": False,
    "workspace_required": "forge",
    "crafting_dc": 13,
    "time": "4 hours",
    "async_cycles": 1,
    "output_item": "iron_sword",
    "output_quantity": 1,
    "study_cost": 2,
    "discovery_sources": ["blacksmith_npc"],
    "narration_cues": {
        "success": "Sparks fly as the blade takes shape.",
        "failure": "The metal cracks and the work is wasted.",
    },
}


def _parsed(recipe_id: str, data: dict) -> dict:
    """The expected parsed recipe: data plus the id from the row key."""
    return {"id": recipe_id, **data}


class TestGetRecipe:
    @pytest.mark.asyncio
    async def test_queries_db_on_miss_and_caches_parsed(self):
        """AC1: first call misses the cache, hits the DB, caches the parsed recipe."""
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value={"data": json.dumps(VALID_RECIPE_DATA)})

        with patch("db._cache_get", new_callable=AsyncMock, return_value=None):
            with patch("db._cache_set", new_callable=AsyncMock) as mock_cache_set:
                with patch("db.get_pool", return_value=mock_pool):
                    result = await recipes.get_recipe("iron_sword")

        expected = _parsed("iron_sword", VALID_RECIPE_DATA)
        assert result == expected
        mock_pool.fetchrow.assert_awaited_once_with("SELECT data FROM recipes WHERE id = $1", "iron_sword")
        # Caches the PARSED dict (parse-once), not the raw row data.
        mock_cache_set.assert_awaited_once_with("recipe:iron_sword", json.dumps(expected))

    @pytest.mark.asyncio
    async def test_second_call_hits_cache_not_db(self):
        """AC1: called twice, the second call returns from cache without a DB query."""
        expected = _parsed("iron_sword", VALID_RECIPE_DATA)
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value={"data": json.dumps(VALID_RECIPE_DATA)})
        # Cache miss on first read, hit (parsed payload) on second.
        cache_get = AsyncMock(side_effect=[None, json.dumps(expected)])

        with patch("db._cache_get", cache_get):
            with patch("db._cache_set", new_callable=AsyncMock):
                with patch("db.get_pool", return_value=mock_pool):
                    first = await recipes.get_recipe("iron_sword")
                    second = await recipes.get_recipe("iron_sword")

        assert first == expected
        assert second == expected
        mock_pool.fetchrow.assert_awaited_once()  # DB hit only on the miss

    @pytest.mark.asyncio
    async def test_returns_cached_directly(self):
        """AC1: a cache hit returns the parsed recipe without touching the pool."""
        expected = _parsed("iron_sword", VALID_RECIPE_DATA)
        with patch("db._cache_get", new_callable=AsyncMock, return_value=json.dumps(expected)) as cg:
            result = await recipes.get_recipe("iron_sword")
        assert result == expected
        cg.assert_awaited_once_with("recipe:iron_sword")

    @pytest.mark.asyncio
    async def test_returns_none_when_absent(self):
        """AC1b: unknown recipe id -> None (no silent default)."""
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value=None)
        with patch("db._cache_get", new_callable=AsyncMock, return_value=None):
            with patch("db.get_pool", return_value=mock_pool):
                result = await recipes.get_recipe("mithril_blade")
        assert result is None


class TestListRecipes:
    @pytest.mark.asyncio
    async def test_queries_db_on_miss_and_caches_all(self):
        """AC2: returns all parsed recipes and caches them under recipes:all."""
        rows = [
            {"id": "iron_sword", "data": json.dumps(VALID_RECIPE_DATA)},
            {"id": "oak_shield", "data": json.dumps({**VALID_RECIPE_DATA, "name": "Oak Shield"})},
        ]
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=rows)

        with patch("db._cache_get", new_callable=AsyncMock, return_value=None):
            with patch("db._cache_set", new_callable=AsyncMock) as mock_cache_set:
                with patch("db.get_pool", return_value=mock_pool):
                    result = await recipes.list_recipes()

        expected = [
            _parsed("iron_sword", VALID_RECIPE_DATA),
            _parsed("oak_shield", {**VALID_RECIPE_DATA, "name": "Oak Shield"}),
        ]
        assert result == expected
        mock_pool.fetch.assert_awaited_once_with("SELECT id, data FROM recipes ORDER BY id")
        mock_cache_set.assert_awaited_once_with("recipes:all", json.dumps(expected))

    @pytest.mark.asyncio
    async def test_returns_cached_directly(self):
        """AC2: a cache hit returns the parsed list without touching the pool."""
        expected = [_parsed("iron_sword", VALID_RECIPE_DATA)]
        with patch("db._cache_get", new_callable=AsyncMock, return_value=json.dumps(expected)) as cg:
            result = await recipes.list_recipes()
        assert result == expected
        cg.assert_awaited_once_with("recipes:all")


class TestParseRecipeRow:
    """AC3: fail loud on any missing/invalid required field — no silent default."""

    def test_valid_row_round_trips(self):
        assert recipes.parse_recipe_row("iron_sword", VALID_RECIPE_DATA) == _parsed("iron_sword", VALID_RECIPE_DATA)

    def test_rejects_non_object(self):
        with pytest.raises(ValueError, match=r"recipes\[x\].data"):
            recipes.parse_recipe_row("x", ["not", "an", "object"])

    def test_missing_required_field_fails_loud(self):
        data = {k: v for k, v in VALID_RECIPE_DATA.items() if k != "crafting_dc"}
        with pytest.raises(ValueError, match=r"recipes\[iron_sword\].crafting_dc"):
            recipes.parse_recipe_row("iron_sword", data)

    def test_rejects_bad_category_enum(self):
        with pytest.raises(ValueError, match=r"category"):
            recipes.parse_recipe_row("x", {**VALID_RECIPE_DATA, "category": "potion"})

    def test_rejects_bad_tier_enum(self):
        with pytest.raises(ValueError, match=r"tier"):
            recipes.parse_recipe_row("x", {**VALID_RECIPE_DATA, "tier": "legendary"})

    def test_rejects_bad_workspace_enum(self):
        with pytest.raises(ValueError, match=r"workspace_required"):
            recipes.parse_recipe_row("x", {**VALID_RECIPE_DATA, "workspace_required": "kitchen"})

    def test_rejects_float_crafting_dc(self):
        with pytest.raises(ValueError, match=r"crafting_dc"):
            recipes.parse_recipe_row("x", {**VALID_RECIPE_DATA, "crafting_dc": 13.5})

    def test_rejects_bool_as_int_count(self):
        # bool is an int subclass in Python — must be rejected for count fields.
        with pytest.raises(ValueError, match=r"output_quantity"):
            recipes.parse_recipe_row("x", {**VALID_RECIPE_DATA, "output_quantity": True})

    def test_rejects_negative_study_cost(self):
        with pytest.raises(ValueError, match=r"study_cost"):
            recipes.parse_recipe_row("x", {**VALID_RECIPE_DATA, "study_cost": -1})

    def test_rejects_zero_crafting_dc(self):
        with pytest.raises(ValueError, match=r"crafting_dc"):
            recipes.parse_recipe_row("x", {**VALID_RECIPE_DATA, "crafting_dc": 0})

    def test_rejects_empty_output_item(self):
        with pytest.raises(ValueError, match=r"output_item"):
            recipes.parse_recipe_row("x", {**VALID_RECIPE_DATA, "output_item": ""})

    def test_rejects_non_list_materials(self):
        with pytest.raises(ValueError, match=r"materials"):
            recipes.parse_recipe_row("x", {**VALID_RECIPE_DATA, "materials": {}})

    def test_rejects_bad_material_tier_minimum(self):
        bad = {
            **VALID_RECIPE_DATA,
            "materials": [{"material_id": "iron_ingot", "quantity": 1, "tier_minimum": 5, "substitutable": True}],
        }
        with pytest.raises(ValueError, match=r"tier_minimum"):
            recipes.parse_recipe_row("x", bad)

    def test_rejects_material_missing_substitutable(self):
        bad = {**VALID_RECIPE_DATA, "materials": [{"material_id": "iron_ingot", "quantity": 1, "tier_minimum": 1}]}
        with pytest.raises(ValueError, match=r"substitutable"):
            recipes.parse_recipe_row("x", bad)

    def test_rejects_empty_material_id(self):
        bad = {
            **VALID_RECIPE_DATA,
            "materials": [{"material_id": "", "quantity": 1, "tier_minimum": 1, "substitutable": True}],
        }
        with pytest.raises(ValueError, match=r"material_id"):
            recipes.parse_recipe_row("x", bad)

    def test_rejects_empty_narration_cues(self):
        with pytest.raises(ValueError, match=r"narration_cues"):
            recipes.parse_recipe_row("x", {**VALID_RECIPE_DATA, "narration_cues": {}})

    def test_rejects_non_string_narration_cue(self):
        with pytest.raises(ValueError, match=r"narration_cues"):
            recipes.parse_recipe_row("x", {**VALID_RECIPE_DATA, "narration_cues": {"success": 1}})

    def test_rejects_non_string_discovery_source(self):
        with pytest.raises(ValueError, match=r"discovery_sources"):
            recipes.parse_recipe_row("x", {**VALID_RECIPE_DATA, "discovery_sources": ["ok", 7]})

    def test_unhashable_category_fails_loud_not_typeerror(self):
        # A JSON array/object for an enum field must raise the contractual
        # ValueError, not a TypeError from the set-membership check.
        with pytest.raises(ValueError, match=r"category"):
            recipes.parse_recipe_row("x", {**VALID_RECIPE_DATA, "category": []})

    def test_unhashable_tier_fails_loud_not_typeerror(self):
        with pytest.raises(ValueError, match=r"tier"):
            recipes.parse_recipe_row("x", {**VALID_RECIPE_DATA, "tier": {}})

    def test_unhashable_workspace_fails_loud_not_typeerror(self):
        with pytest.raises(ValueError, match=r"workspace_required"):
            recipes.parse_recipe_row("x", {**VALID_RECIPE_DATA, "workspace_required": []})

    def test_unhashable_material_tier_minimum_fails_loud_not_typeerror(self):
        bad = {
            **VALID_RECIPE_DATA,
            "materials": [{"material_id": "iron_ingot", "quantity": 1, "tier_minimum": [], "substitutable": True}],
        }
        with pytest.raises(ValueError, match=r"tier_minimum"):
            recipes.parse_recipe_row("x", bad)
