"""Tests for the Python recipe_slots accessor (M5.1, concern d125d022f084).

Mirrors test_recipes.py's mocked-pool style: patch db._cache_get / _cache_set /
db.get_pool. recipe_slots is reference data seeded inline by migration 019;
loading it from the DB (rather than a hardcoded Python dict) keeps the slot caps
in one canonical place. The real-DB load path is exercised against a testcontainer
in tests/acceptance/test_recipe_slots_loading.py.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

import recipe_slots

# The four seeded rows' `data` payloads (migration 019 recipe_slots seed).
SEED_ROWS = [
    {"id": "untrained", "data": json.dumps({"max_recipe_tier": "basic", "known_recipe_slots": 3})},
    {"id": "trained", "data": json.dumps({"max_recipe_tier": "trained", "known_recipe_slots": 8})},
    {"id": "expert", "data": json.dumps({"max_recipe_tier": "expert", "known_recipe_slots": 15})},
    {"id": "master", "data": json.dumps({"max_recipe_tier": "master", "known_recipe_slots": None})},
]

EXPECTED = {
    "untrained": {"max_recipe_tier": "basic", "known_recipe_slots": 3},
    "trained": {"max_recipe_tier": "trained", "known_recipe_slots": 8},
    "expert": {"max_recipe_tier": "expert", "known_recipe_slots": 15},
    "master": {"max_recipe_tier": "master", "known_recipe_slots": None},
}


class TestGetRecipeSlots:
    @pytest.mark.asyncio
    async def test_queries_db_on_miss_and_caches(self):
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=SEED_ROWS)

        with patch("db._cache_get", new_callable=AsyncMock, return_value=None):
            with patch("db._cache_set", new_callable=AsyncMock) as mock_cache_set:
                with patch("db.get_pool", return_value=mock_pool):
                    result = await recipe_slots.get_recipe_slots()

        assert result == EXPECTED
        mock_pool.fetch.assert_awaited_once_with("SELECT id, data FROM recipe_slots")
        mock_cache_set.assert_awaited_once_with("recipe_slots:all", json.dumps(EXPECTED))

    @pytest.mark.asyncio
    async def test_returns_cached_directly(self):
        with patch("db._cache_get", new_callable=AsyncMock, return_value=json.dumps(EXPECTED)) as cg:
            result = await recipe_slots.get_recipe_slots()
        assert result == EXPECTED
        cg.assert_awaited_once_with("recipe_slots:all")

    @pytest.mark.asyncio
    async def test_null_slot_cap_parses_to_none(self):
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[SEED_ROWS[3]])  # master: null
        with patch("db._cache_get", new_callable=AsyncMock, return_value=None):
            with patch("db._cache_set", new_callable=AsyncMock):
                with patch("db.get_pool", return_value=mock_pool):
                    result = await recipe_slots.get_recipe_slots()
        assert result["master"]["known_recipe_slots"] is None


class TestParseRecipeSlotRow:
    """Fail loud on any missing/invalid field — no silent default."""

    def test_valid_row_round_trips(self):
        assert recipe_slots.parse_recipe_slot_row(
            "untrained", {"max_recipe_tier": "basic", "known_recipe_slots": 3}
        ) == {
            "max_recipe_tier": "basic",
            "known_recipe_slots": 3,
        }

    def test_null_cap_allowed_for_master(self):
        parsed = recipe_slots.parse_recipe_slot_row("master", {"max_recipe_tier": "master", "known_recipe_slots": None})
        assert parsed["known_recipe_slots"] is None

    def test_null_cap_rejected_for_non_master(self):
        # A null (unlimited) cap is only valid for master — a null on untrained
        # would silently grant unlimited basic recipes, so it must fail loud.
        with pytest.raises(ValueError, match=r"only valid for the master tier"):
            recipe_slots.parse_recipe_slot_row("untrained", {"max_recipe_tier": "basic", "known_recipe_slots": None})

    def test_rejects_non_object(self):
        with pytest.raises(ValueError, match=r"recipe_slots\[untrained\]"):
            recipe_slots.parse_recipe_slot_row("untrained", ["nope"])

    def test_rejects_bad_max_recipe_tier(self):
        with pytest.raises(ValueError, match=r"max_recipe_tier"):
            recipe_slots.parse_recipe_slot_row("untrained", {"max_recipe_tier": "legendary", "known_recipe_slots": 3})

    def test_rejects_missing_max_recipe_tier(self):
        with pytest.raises(ValueError, match=r"max_recipe_tier"):
            recipe_slots.parse_recipe_slot_row("untrained", {"known_recipe_slots": 3})

    def test_rejects_negative_slot_cap(self):
        with pytest.raises(ValueError, match=r"known_recipe_slots"):
            recipe_slots.parse_recipe_slot_row("untrained", {"max_recipe_tier": "basic", "known_recipe_slots": -1})

    def test_rejects_bool_slot_cap(self):
        # bool is an int subclass in Python — a count field is never True/False.
        with pytest.raises(ValueError, match=r"known_recipe_slots"):
            recipe_slots.parse_recipe_slot_row("untrained", {"max_recipe_tier": "basic", "known_recipe_slots": True})

    def test_rejects_missing_slot_cap_key(self):
        with pytest.raises(ValueError, match=r"known_recipe_slots"):
            recipe_slots.parse_recipe_slot_row("untrained", {"max_recipe_tier": "basic"})
