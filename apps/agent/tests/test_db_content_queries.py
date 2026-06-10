"""Unit tests for db_content_queries.get_faction (story-008 stance-gate read seam).

Mocked cache + pool (like tests/database/): a cache hit returns without a DB read; a miss
falls through to the factions table and back-fills the cache; a missing row returns None.
Real SQL correctness is exercised against the testcontainer in the acceptance suite.
"""

import json
from unittest.mock import AsyncMock, patch

import db_content_queries


class TestGetFaction:
    @patch("db_content_queries.db")
    async def test_returns_parsed_row_on_cache_miss_and_backfills(self, mock_db):
        mock_db._cache_get = AsyncMock(return_value=None)
        mock_db._cache_set = AsyncMock()
        pool = AsyncMock()
        pool.fetchrow = AsyncMock(return_value={"data": json.dumps({"id": "thornwatch", "reputation_tiers": {}})})
        mock_db.get_pool = AsyncMock(return_value=pool)

        result = await db_content_queries.get_faction("thornwatch")
        assert result is not None
        assert result["id"] == "thornwatch"
        assert "factions" in pool.fetchrow.call_args.args[0]
        mock_db._cache_set.assert_awaited_once()

    @patch("db_content_queries.db")
    async def test_returns_cached_value_without_db(self, mock_db):
        mock_db._cache_get = AsyncMock(return_value=json.dumps({"id": "thornwatch"}))
        mock_db.get_pool = AsyncMock()
        result = await db_content_queries.get_faction("thornwatch")
        assert result is not None
        assert result["id"] == "thornwatch"
        mock_db.get_pool.assert_not_called()

    @patch("db_content_queries.db")
    async def test_none_when_not_found(self, mock_db):
        mock_db._cache_get = AsyncMock(return_value=None)
        pool = AsyncMock()
        pool.fetchrow = AsyncMock(return_value=None)
        mock_db.get_pool = AsyncMock(return_value=pool)
        assert await db_content_queries.get_faction("nope") is None
