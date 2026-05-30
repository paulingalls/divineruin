"""Tests for the Python materials-catalog accessor (story-004, M5.2).

Mirrors test_recipes.py's mocked-pool style: patch db._cache_get / _cache_set /
db.get_pool. The agent reads materials from the DB (constraint 8508fdb1abc3) the
same way it reads recipes — material:<id> and materials:all cache keys, fail-loud
parse via parse_material_row. get_materials_catalog feeds the pre-flight pipeline's
Check 4 + the craft-consume allocator (material_id -> {category, tier}).
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

import materials

# A materials_catalog row's `data` payload (id is the row key, passed separately).
VALID_MATERIAL_DATA = {
    "name": "Iron Ore",
    "category": "metal",
    "tier": 1,
    "rarity": "common",
    "source": "Mined from hill seams.",
    "weight": 2.0,
    "description": "Rust-streaked rock.",
}


class TestParseMaterialRow:
    def test_parses_a_valid_row_to_id_category_tier(self):
        parsed = materials.parse_material_row("iron_ore", VALID_MATERIAL_DATA)
        assert parsed == {"id": "iron_ore", "category": "metal", "tier": 1}

    def test_rejects_non_dict(self):
        with pytest.raises(ValueError, match="iron_ore"):
            materials.parse_material_row("iron_ore", ["not", "a", "dict"])

    def test_rejects_missing_or_empty_category(self):
        with pytest.raises(ValueError, match="category"):
            materials.parse_material_row("iron_ore", {**VALID_MATERIAL_DATA, "category": ""})

    def test_rejects_tier_out_of_range(self):
        with pytest.raises(ValueError, match="tier"):
            materials.parse_material_row("iron_ore", {**VALID_MATERIAL_DATA, "tier": 5})

    def test_rejects_bool_tier(self):
        # bool is an int subclass in Python — a tier is never True/False.
        with pytest.raises(ValueError, match="tier"):
            materials.parse_material_row("iron_ore", {**VALID_MATERIAL_DATA, "tier": True})


class TestGetMaterial:
    @patch("materials.db")
    async def test_returns_parsed_material_on_cache_miss(self, mock_db):
        mock_db._cache_get = AsyncMock(return_value=None)
        mock_db._cache_set = AsyncMock()
        pool = AsyncMock()
        pool.fetchrow = AsyncMock(return_value={"data": json.dumps(VALID_MATERIAL_DATA)})
        mock_db.get_pool = AsyncMock(return_value=pool)

        result = await materials.get_material("iron_ore")
        assert result == {"id": "iron_ore", "category": "metal", "tier": 1}
        mock_db._cache_set.assert_awaited_once()

    @patch("materials.db")
    async def test_returns_none_for_unknown_material(self, mock_db):
        mock_db._cache_get = AsyncMock(return_value=None)
        pool = AsyncMock()
        pool.fetchrow = AsyncMock(return_value=None)
        mock_db.get_pool = AsyncMock(return_value=pool)
        assert await materials.get_material("nope") is None

    @patch("materials.db")
    async def test_serves_cached_parsed_material(self, mock_db):
        cached = {"id": "iron_ore", "category": "metal", "tier": 1}
        mock_db._cache_get = AsyncMock(return_value=json.dumps(cached))
        assert await materials.get_material("iron_ore") == cached


class TestGetMaterialsCatalog:
    @patch("materials.db")
    async def test_builds_id_to_category_tier_map(self, mock_db):
        mock_db._cache_get = AsyncMock(return_value=None)
        mock_db._cache_set = AsyncMock()
        pool = AsyncMock()
        pool.fetch = AsyncMock(
            return_value=[
                {"id": "iron_ore", "data": json.dumps(VALID_MATERIAL_DATA)},
                {"id": "oak_wood", "data": json.dumps({**VALID_MATERIAL_DATA, "category": "wood", "tier": 2})},
            ]
        )
        mock_db.get_pool = AsyncMock(return_value=pool)

        catalog = await materials.get_materials_catalog()
        assert catalog["iron_ore"] == {"id": "iron_ore", "category": "metal", "tier": 1}
        assert catalog["oak_wood"]["category"] == "wood"
        assert catalog["oak_wood"]["tier"] == 2
