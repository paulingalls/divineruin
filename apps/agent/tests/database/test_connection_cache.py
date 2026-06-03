"""Tests for connection pool lifecycle, Redis cache, and cached content queries."""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import db
import db_content_queries


class TestConnectionPoolManagement:
    """Test connection pool initialization and lifecycle."""

    @pytest.mark.asyncio
    async def test_get_pool_creates_pool_on_first_call(self):
        """get_pool should create a pool on first access."""
        db._pool = None
        with patch.dict(os.environ, {"DATABASE_URL": "postgres://test"}):
            with patch("asyncpg.create_pool", new_callable=AsyncMock) as mock_create:
                mock_pool = MagicMock()
                mock_create.return_value = mock_pool

                result = await db.get_pool()

                mock_create.assert_called_once_with("postgres://test", min_size=2, max_size=5)
                assert result is mock_pool
                assert db._pool is mock_pool

    @pytest.mark.asyncio
    async def test_get_pool_reuses_existing_pool(self):
        """get_pool should return cached pool on subsequent calls."""
        mock_pool = MagicMock()
        db._pool = mock_pool

        result = await db.get_pool()

        assert result is mock_pool

    @pytest.mark.asyncio
    async def test_get_redis_creates_redis_on_first_call(self):
        """get_redis should create redis client on first access."""
        db._redis = None
        with patch.dict(os.environ, {"REDIS_URL": "redis://test:6379"}):
            with patch("redis.asyncio.from_url") as mock_from_url:
                mock_redis = MagicMock()
                mock_from_url.return_value = mock_redis

                result = await db.get_redis()

                mock_from_url.assert_called_once_with(
                    "redis://test:6379",
                    decode_responses=True,
                )
                assert result is mock_redis
                assert db._redis is mock_redis

    @pytest.mark.asyncio
    async def test_get_redis_uses_default_url_if_not_set(self):
        """get_redis should default to localhost if REDIS_URL not set."""
        db._redis = None
        with patch.dict(os.environ, {}, clear=True):
            with patch("redis.asyncio.from_url") as mock_from_url:
                mock_redis = MagicMock()
                mock_from_url.return_value = mock_redis

                await db.get_redis()

                mock_from_url.assert_called_once_with(
                    "redis://localhost:56379",
                    decode_responses=True,
                )

    @pytest.mark.asyncio
    async def test_get_redis_reuses_existing_client(self):
        """get_redis should return cached client on subsequent calls."""
        mock_redis = MagicMock()
        db._redis = mock_redis

        result = await db.get_redis()

        assert result is mock_redis

    @pytest.mark.asyncio
    async def test_close_all_closes_pool_and_redis(self):
        """close_all should close both pool and redis if initialized."""
        mock_pool = MagicMock()
        mock_pool.close = AsyncMock()
        mock_redis = MagicMock()
        mock_redis.aclose = AsyncMock()

        db._pool = mock_pool
        db._redis = mock_redis

        await db.close_all()

        mock_pool.close.assert_awaited_once()
        mock_redis.aclose.assert_awaited_once()
        assert db._pool is None
        assert db._redis is None

    @pytest.mark.asyncio
    async def test_close_all_handles_none_gracefully(self):
        """close_all should not error if pool/redis are None."""
        db._pool = None
        db._redis = None

        await db.close_all()  # Should not raise

        assert db._pool is None
        assert db._redis is None


class TestCacheOperations:
    """Test Redis cache get/set with fallback behavior."""

    @pytest.mark.asyncio
    async def test_cache_get_returns_cached_value(self):
        """_cache_get should return value from Redis."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value='{"cached": "data"}')

        with patch("db.get_redis", return_value=mock_redis):
            result = await db._cache_get("test_key")

        assert result == '{"cached": "data"}'
        mock_redis.get.assert_awaited_once_with("test_key")

    @pytest.mark.asyncio
    async def test_cache_get_returns_none_on_miss(self):
        """_cache_get should return None if key not found."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch("db.get_redis", return_value=mock_redis):
            result = await db._cache_get("missing_key")

        assert result is None

    @pytest.mark.asyncio
    async def test_cache_get_falls_through_on_redis_error(self):
        """_cache_get should return None on Redis failure."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=ConnectionError("Redis down"))

        with patch("db.get_redis", return_value=mock_redis):
            result = await db._cache_get("test_key")

        assert result is None

    @pytest.mark.asyncio
    async def test_cache_set_writes_to_redis(self):
        """_cache_set should write value to Redis with TTL."""
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()

        with patch("db.get_redis", return_value=mock_redis):
            await db._cache_set("test_key", '{"value": 123}')

        mock_redis.set.assert_awaited_once_with("test_key", '{"value": 123}', ex=db.CACHE_TTL)

    @pytest.mark.asyncio
    async def test_cache_set_ignores_redis_errors(self):
        """_cache_set should not raise on Redis failure."""
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(side_effect=ConnectionError("Redis down"))

        with patch("db.get_redis", return_value=mock_redis):
            await db._cache_set("test_key", "value")  # Should not raise


class TestCachedContentQueries:
    """Test cached queries for static content (locations, NPCs, items, quests)."""

    @pytest.mark.asyncio
    async def test_get_location_returns_cached_data(self):
        """get_location should return cached location if available."""
        cached_data = {"id": "tavern", "name": "The Rusty Sword"}

        with patch("db._cache_get", new_callable=AsyncMock) as mock_cache_get:
            mock_cache_get.return_value = json.dumps(cached_data)

            result = await db_content_queries.get_location("tavern")

        assert result == cached_data
        mock_cache_get.assert_awaited_once_with("location:tavern")

    @pytest.mark.asyncio
    async def test_get_location_queries_db_on_cache_miss(self):
        """get_location should query DB and cache result on miss."""
        location_data = {"id": "tavern", "name": "The Rusty Sword"}
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value={"data": json.dumps(location_data)})

        with patch("db._cache_get", new_callable=AsyncMock, return_value=None):
            with patch("db._cache_set", new_callable=AsyncMock) as mock_cache_set:
                with patch("db.get_pool", return_value=mock_pool):
                    result = await db_content_queries.get_location("tavern")

        assert result == location_data
        mock_pool.fetchrow.assert_awaited_once_with("SELECT data FROM locations WHERE id = $1", "tavern")
        mock_cache_set.assert_awaited_once_with("location:tavern", json.dumps(location_data))

    @pytest.mark.asyncio
    async def test_get_location_returns_none_if_not_found(self):
        """get_location should return None if location doesn't exist."""
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value=None)

        with patch("db._cache_get", new_callable=AsyncMock, return_value=None):
            with patch("db.get_pool", return_value=mock_pool):
                result = await db_content_queries.get_location("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_npc_returns_cached_data(self):
        """get_npc should return cached NPC if available."""
        cached_data = {"id": "torin", "name": "Guildmaster Torin"}

        with patch("db._cache_get", new_callable=AsyncMock) as mock_cache_get:
            mock_cache_get.return_value = json.dumps(cached_data)

            result = await db_content_queries.get_npc("torin")

        assert result == cached_data
        mock_cache_get.assert_awaited_once_with("npc:torin")

    @pytest.mark.asyncio
    async def test_get_item_queries_db_on_cache_miss(self):
        """get_item should query DB and cache result on miss."""
        item_data = {"id": "sword", "name": "Steel Longsword"}
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value={"data": json.dumps(item_data)})

        with patch("db._cache_get", new_callable=AsyncMock, return_value=None):
            with patch("db._cache_set", new_callable=AsyncMock):
                with patch("db.get_pool", return_value=mock_pool):
                    result = await db_content_queries.get_item("sword")

        assert result == item_data

    @pytest.mark.asyncio
    async def test_get_quest_returns_cached_quest(self):
        """get_quest should return cached quest data."""
        quest_data = {"id": "hollow_threat", "name": "The Hollow Threat"}

        with patch("db._cache_get", new_callable=AsyncMock) as mock_cache_get:
            mock_cache_get.return_value = json.dumps(quest_data)

            result = await db_content_queries.get_quest("hollow_threat")

        assert result == quest_data
        mock_cache_get.assert_awaited_once_with("quest:hollow_threat")

    @pytest.mark.asyncio
    async def test_search_lore_queries_database(self):
        """search_lore should query DB with keyword pattern."""
        lore_entries = [
            {"title": "The Veil", "content": "..."},
            {"title": "Hollow Origins", "content": "..."},
        ]
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[{"data": json.dumps(entry)} for entry in lore_entries])

        with patch("db.get_pool", return_value=mock_pool):
            result = await db_content_queries.search_lore("Hollow", limit=5)

        assert result == lore_entries
        mock_pool.fetch.assert_awaited_once_with(
            "SELECT data FROM lore_entries WHERE data::text ILIKE $1 LIMIT $2",
            "%Hollow%",
            5,
        )

    @pytest.mark.asyncio
    async def test_search_lore_escapes_ilike_metacharacters(self):
        """search_lore should escape %, _, and \\ in keywords."""
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[])

        with patch("db.get_pool", return_value=mock_pool):
            await db_content_queries.search_lore("100%_done", limit=5)

        call_args = mock_pool.fetch.call_args[0]
        assert call_args[1] == "%100\\%\\_done%"

    @pytest.mark.asyncio
    async def test_get_errand_template_returns_cached_data(self):
        """get_errand_template should return cached template if available."""
        cached_data = {"id": "scout", "name": "Scouting Mission", "duration_min_seconds": 14400}

        with patch("db._cache_get", new_callable=AsyncMock) as mock_cache_get:
            mock_cache_get.return_value = json.dumps(cached_data)

            result = await db_content_queries.get_errand_template("scout")

        assert result == cached_data
        mock_cache_get.assert_awaited_once_with("errand_template:scout")

    @pytest.mark.asyncio
    async def test_get_errand_template_queries_db_on_cache_miss(self):
        """get_errand_template should query DB and cache result on miss."""
        template = {
            "id": "scout",
            "name": "Scouting Mission",
            "duration_min_seconds": 14400,
            "duration_max_seconds": 28800,
            "valid_destinations": ["millhaven"],
            "blocked_companions": [],
        }
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value={"data": json.dumps(template)})

        with patch("db._cache_get", new_callable=AsyncMock, return_value=None):
            with patch("db._cache_set", new_callable=AsyncMock) as mock_cache_set:
                with patch("db.get_pool", return_value=mock_pool):
                    result = await db_content_queries.get_errand_template("scout")

        assert result == template
        mock_pool.fetchrow.assert_awaited_once_with("SELECT data FROM errand_templates WHERE id = $1", "scout")
        mock_cache_set.assert_awaited_once_with("errand_template:scout", json.dumps(template))

    @pytest.mark.asyncio
    async def test_get_errand_template_returns_none_if_not_found(self):
        """get_errand_template should return None for an unknown errand type."""
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value=None)

        with patch("db._cache_get", new_callable=AsyncMock, return_value=None):
            with patch("db.get_pool", return_value=mock_pool):
                result = await db_content_queries.get_errand_template("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_list_errand_templates_queries_db_on_cache_miss(self):
        """list_errand_templates should query DB and cache the full list on miss."""
        templates = [
            {"id": "acquire", "name": "Acquire Supplies"},
            {"id": "scout", "name": "Scouting Mission"},
        ]
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[{"data": json.dumps(t)} for t in templates])

        with patch("db._cache_get", new_callable=AsyncMock, return_value=None):
            with patch("db._cache_set", new_callable=AsyncMock) as mock_cache_set:
                with patch("db.get_pool", return_value=mock_pool):
                    result = await db_content_queries.list_errand_templates()

        assert result == templates
        mock_pool.fetch.assert_awaited_once_with("SELECT data FROM errand_templates ORDER BY id")
        mock_cache_set.assert_awaited_once_with("errand_templates:all", json.dumps(templates))


class TestTransactionContext:
    """Test transaction context manager."""

    @pytest.mark.asyncio
    async def test_transaction_acquires_connection_and_opens_transaction(self):
        """transaction() should acquire connection and start transaction."""
        mock_conn = MagicMock()
        mock_txn = MagicMock()
        mock_txn.__aenter__ = AsyncMock(return_value=None)
        mock_txn.__aexit__ = AsyncMock(return_value=None)
        mock_conn.transaction.return_value = mock_txn

        mock_pool = MagicMock()
        mock_acquire = MagicMock()
        mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire.return_value = mock_acquire

        with patch("db.get_pool", new_callable=AsyncMock, return_value=mock_pool):
            async with db.transaction() as conn:
                assert conn is mock_conn

        mock_conn.transaction.assert_called_once()
        mock_txn.__aenter__.assert_awaited_once()
        mock_txn.__aexit__.assert_awaited_once()
