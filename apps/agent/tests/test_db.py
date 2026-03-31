"""Tests for database connection layer and cache."""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import db


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
                    "redis://localhost:6379",
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

            result = await db.get_location("tavern")

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
                    result = await db.get_location("tavern")

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
                result = await db.get_location("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_npc_returns_cached_data(self):
        """get_npc should return cached NPC if available."""
        cached_data = {"id": "torin", "name": "Guildmaster Torin"}

        with patch("db._cache_get", new_callable=AsyncMock) as mock_cache_get:
            mock_cache_get.return_value = json.dumps(cached_data)

            result = await db.get_npc("torin")

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
                    result = await db.get_item("sword")

        assert result == item_data

    @pytest.mark.asyncio
    async def test_get_quest_returns_cached_quest(self):
        """get_quest should return cached quest data."""
        quest_data = {"id": "hollow_threat", "name": "The Hollow Threat"}

        with patch("db._cache_get", new_callable=AsyncMock) as mock_cache_get:
            mock_cache_get.return_value = json.dumps(quest_data)

            result = await db.get_quest("hollow_threat")

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
            result = await db.search_lore("Hollow", limit=5)

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
            await db.search_lore("100%_done", limit=5)

        call_args = mock_pool.fetch.call_args[0]
        assert call_args[1] == "%100\\%\\_done%"


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


class TestStateQueries:
    """Test non-cached state queries (player, NPC dispositions, inventory)."""

    @pytest.mark.asyncio
    async def test_get_player_returns_player_data(self):
        """get_player should query and return player data."""
        player_data = {"player_id": "p1", "name": "Hero", "level": 5}
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value={"data": json.dumps(player_data)})

        with patch("db.get_pool", return_value=mock_pool):
            result = await db.get_player("p1")

        assert result == player_data
        mock_pool.fetchrow.assert_awaited_once_with("SELECT data FROM players WHERE player_id = $1", "p1")

    @pytest.mark.asyncio
    async def test_get_player_with_for_update_adds_lock(self):
        """get_player with for_update=True should add FOR UPDATE clause."""
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value={"data": '{"level": 5}'})

        with patch("db.get_pool", return_value=mock_pool):
            await db.get_player("p1", for_update=True)

        call_args = mock_pool.fetchrow.call_args[0]
        assert "FOR UPDATE" in call_args[0]

    @pytest.mark.asyncio
    async def test_get_npc_disposition_returns_disposition(self):
        """get_npc_disposition should return disposition string."""
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(
            return_value={"data": json.dumps({"disposition": "friendly", "reason": "helped"})}
        )

        with patch("db.get_pool", return_value=mock_pool):
            result = await db.get_npc_disposition("torin", "p1")

        assert result == "friendly"

    @pytest.mark.asyncio
    async def test_get_npc_dispositions_batch_fetches(self):
        """get_npc_dispositions should batch-fetch multiple NPCs."""
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(
            return_value=[
                {"npc_id": "npc1", "data": json.dumps({"disposition": "friendly"})},
                {"npc_id": "npc2", "data": json.dumps({"disposition": "hostile"})},
            ]
        )

        with patch("db.get_pool", return_value=mock_pool):
            result = await db.get_npc_dispositions(["npc1", "npc2"], "p1")

        assert result == {"npc1": "friendly", "npc2": "hostile"}

    @pytest.mark.asyncio
    async def test_get_npc_dispositions_empty_list_returns_empty_dict(self):
        """get_npc_dispositions with empty list should return empty dict."""
        result = await db.get_npc_dispositions([], "p1")
        assert result == {}

    @pytest.mark.asyncio
    async def test_get_player_inventory_joins_items(self):
        """get_player_inventory should join items and inventory slots."""
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(
            return_value=[
                {
                    "item_data": json.dumps({"id": "sword", "name": "Steel Sword"}),
                    "slot_data": json.dumps({"quantity": 1, "equipped": True}),
                }
            ]
        )

        with patch("db.get_pool", return_value=mock_pool):
            result = await db.get_player_inventory("p1")

        assert len(result) == 1
        assert result[0]["id"] == "sword"
        assert result[0]["slot_info"]["equipped"] is True

    @pytest.mark.asyncio
    async def test_get_npcs_at_location_queries_schedule(self):
        """get_npcs_at_location should query NPCs by schedule."""
        npc_data = {"id": "torin", "name": "Torin", "schedule": {"evening": "tavern"}}
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[{"id": "torin", "data": json.dumps(npc_data)}])

        with patch("db.get_pool", return_value=mock_pool):
            result = await db.get_npcs_at_location("tavern")

        assert len(result) == 1
        assert result[0]["id"] == "torin"
        assert result[0]["name"] == "Torin"

    @pytest.mark.asyncio
    async def test_get_active_player_quests_joins_quest_data(self):
        """get_active_player_quests should join player quest state with quest data."""
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(
            return_value=[
                {
                    "quest_id": "q1",
                    "pq_data": json.dumps({"current_stage": 2}),
                    "q_data": json.dumps(
                        {
                            "name": "The Quest",
                            "stages": ["stage1", "stage2", "stage3"],
                            "global_hints": ["hint1"],
                        }
                    ),
                }
            ]
        )

        with patch("db.get_pool", return_value=mock_pool):
            result = await db.get_active_player_quests("p1")

        assert len(result) == 1
        assert result[0]["quest_id"] == "q1"
        assert result[0]["quest_name"] == "The Quest"
        assert result[0]["current_stage"] == 2
        assert len(result[0]["stages"]) == 3


class TestStateMutations:
    """Test state mutation functions."""

    @pytest.mark.asyncio
    async def test_update_player_location_updates_jsonb(self):
        """update_player_location should update location_id field."""
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock()

        with patch("db.get_pool", return_value=mock_pool):
            await db.update_player_location("p1", "tavern")

        mock_pool.execute.assert_awaited_once()
        call_args = mock_pool.execute.call_args[0]
        assert "jsonb_set" in call_args[0]
        assert call_args[1] == "p1"
        assert json.loads(call_args[2]) == "tavern"

    @pytest.mark.asyncio
    async def test_update_player_xp_updates_both_fields(self):
        """update_player_xp should update both xp and level."""
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock()

        with patch("db.get_pool", return_value=mock_pool):
            await db.update_player_xp("p1", new_xp=1000, new_level=5)

        call_args = mock_pool.execute.call_args[0]
        assert call_args[1] == "p1"
        assert json.loads(call_args[2]) == 1000
        assert json.loads(call_args[3]) == 5

    @pytest.mark.asyncio
    async def test_add_inventory_item_upserts_quantity(self):
        """add_inventory_item should insert or increment quantity."""
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock()

        with patch("db.get_pool", return_value=mock_pool):
            await db.add_inventory_item("p1", "sword", quantity=2)

        call_args = mock_pool.execute.call_args[0]
        assert "INSERT INTO player_inventory" in call_args[0]
        assert "ON CONFLICT" in call_args[0]
        assert call_args[1] == "p1"
        assert call_args[2] == "sword"

    @pytest.mark.asyncio
    async def test_remove_inventory_item_returns_true_on_success(self):
        """remove_inventory_item should return True if item was deleted."""
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock(return_value="DELETE 1")

        with patch("db.get_pool", return_value=mock_pool):
            result = await db.remove_inventory_item("p1", "sword")

        assert result is True

    @pytest.mark.asyncio
    async def test_remove_inventory_item_returns_false_on_miss(self):
        """remove_inventory_item should return False if item not found."""
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock(return_value="DELETE 0")

        with patch("db.get_pool", return_value=mock_pool):
            result = await db.remove_inventory_item("p1", "nonexistent")

        assert result is False

    @pytest.mark.asyncio
    async def test_set_npc_disposition_upserts_disposition(self):
        """set_npc_disposition should insert or update disposition."""
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock()

        with patch("db.get_pool", return_value=mock_pool):
            await db.set_npc_disposition("npc1", "p1", "friendly", "helped us")

        call_args = mock_pool.execute.call_args[0]
        assert "INSERT INTO npc_dispositions" in call_args[0]
        assert "ON CONFLICT" in call_args[0]
        data = json.loads(call_args[3])
        assert data["disposition"] == "friendly"
        assert data["reason"] == "helped us"

    @pytest.mark.asyncio
    async def test_set_player_quest_upserts_quest_state(self):
        """set_player_quest should insert or update quest state."""
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock()

        quest_data = {"current_stage": 3, "progress": "found clue"}
        with patch("db.get_pool", return_value=mock_pool):
            await db.set_player_quest("p1", "q1", quest_data)

        call_args = mock_pool.execute.call_args[0]
        assert "INSERT INTO player_quests" in call_args[0]
        assert call_args[1] == "p1"
        assert call_args[2] == "q1"
        assert json.loads(call_args[3]) == quest_data

    @pytest.mark.asyncio
    async def test_log_world_event_inserts_event(self):
        """log_world_event should insert event into log."""
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock()

        event_data = {"player_id": "p1", "action": "completed quest"}
        with patch("db.get_pool", return_value=mock_pool):
            await db.log_world_event("quest_complete", event_data)

        call_args = mock_pool.execute.call_args[0]
        assert "INSERT INTO world_events_log" in call_args[0]
        assert call_args[1] == "quest_complete"
        assert json.loads(call_args[2]) == event_data

    @pytest.mark.asyncio
    async def test_upsert_map_progress_inserts_record(self):
        """upsert_map_progress should insert a map progress record."""
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock()

        with patch("db.get_pool", return_value=mock_pool):
            await db.upsert_map_progress("p1", "tavern", ["market", "docks"])

        call_args = mock_pool.execute.call_args[0]
        assert "INSERT INTO player_map_progress" in call_args[0]
        assert "ON CONFLICT" in call_args[0]
        assert "DO NOTHING" in call_args[0]
        assert call_args[1] == "p1"
        assert call_args[2] == "tavern"
        data = json.loads(call_args[3])
        assert data["connections"] == ["market", "docks"]

    @pytest.mark.asyncio
    async def test_upsert_map_progress_uses_provided_conn(self):
        """upsert_map_progress should use the provided connection."""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()

        await db.upsert_map_progress("p1", "tavern", [], conn=mock_conn)

        mock_conn.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_player_map_progress_returns_visited(self):
        """get_player_map_progress should return visited locations."""
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(
            return_value=[
                {"location_id": "tavern", "data": json.dumps({"connections": ["market"]})},
                {"location_id": "market", "data": json.dumps({"connections": ["tavern", "docks"]})},
            ]
        )

        with patch("db.get_pool", return_value=mock_pool):
            result = await db.get_player_map_progress("p1")

        assert len(result) == 2
        assert result[0]["location_id"] == "tavern"
        assert result[0]["connections"] == ["market"]
        assert result[1]["location_id"] == "market"
        assert result[1]["connections"] == ["tavern", "docks"]

    @pytest.mark.asyncio
    async def test_get_player_map_progress_empty(self):
        """get_player_map_progress should return empty list for new player."""
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[])

        with patch("db.get_pool", return_value=mock_pool):
            result = await db.get_player_map_progress("new_player")

        assert result == []

    @pytest.mark.asyncio
    async def test_update_player_portrait_updates_jsonb(self):
        """update_player_portrait should set portrait_url in player data."""
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock()

        with patch("db.get_pool", return_value=mock_pool):
            await db.update_player_portrait("p1", "/api/assets/images/img_abc123")

        call_args = mock_pool.execute.call_args[0]
        assert "jsonb_set" in call_args[0]
        assert "portrait_url" in call_args[0]
        assert call_args[1] == "p1"
        assert json.loads(call_args[2]) == "/api/assets/images/img_abc123"


class TestSessionInitPortraits:
    """Test that get_session_init_payload includes portraits."""

    @pytest.mark.asyncio
    async def test_session_init_includes_portraits(self):
        """get_session_init_payload should include portraits dict."""
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value={"data": json.dumps({"name": "Test", "location_id": "tavern"})})
        mock_pool.fetch = AsyncMock(return_value=[])

        with patch("db.get_pool", return_value=mock_pool):
            with patch("db.get_location", return_value={"id": "tavern", "name": "Tavern"}):
                result = await db.get_session_init_payload("p1")

        assert "portraits" in result
        assert "companion" in result["portraits"]
        assert "npcs" in result["portraits"]
        assert "primary" in result["portraits"]["companion"]
        assert "alert" in result["portraits"]["companion"]
        # Verify NPC portrait URLs are present
        assert "Guildmaster Torin" in result["portraits"]["npcs"]
        assert result["portraits"]["npcs"]["Guildmaster Torin"].startswith("/api/assets/images/npc_")

    def test_build_portraits_produces_valid_urls(self):
        """_build_portraits should produce /api/assets/images/ URLs."""
        result = db._build_portraits(None, "tavern")
        assert result["companion"]["primary"].startswith("/api/assets/images/companion_")
        assert result["companion"]["alert"].startswith("/api/assets/images/companion_")
        for url in result["npcs"].values():
            assert url.startswith("/api/assets/images/npc_")


class TestGetPlayerFlagValue:
    @pytest.mark.asyncio
    async def test_returns_int(self):
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value={"val": "3"})
        with patch("db.get_pool", new_callable=AsyncMock, return_value=mock_pool):
            result = await db.get_player_flag_value("p1", "onboarding_beat")
        assert result == 3
        assert isinstance(result, int)

    @pytest.mark.asyncio
    async def test_returns_bool_true(self):
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value={"val": "true"})
        with patch("db.get_pool", new_callable=AsyncMock, return_value=mock_pool):
            result = await db.get_player_flag_value("p1", "companion_met")
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_bool_false(self):
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value={"val": "false"})
        with patch("db.get_pool", new_callable=AsyncMock, return_value=mock_pool):
            result = await db.get_player_flag_value("p1", "some_flag")
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_string(self):
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value={"val": '"hello"'})
        with patch("db.get_pool", new_callable=AsyncMock, return_value=mock_pool):
            result = await db.get_player_flag_value("p1", "greeting")
        assert result == "hello"
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_returns_none_when_missing(self):
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value={"val": None})
        with patch("db.get_pool", new_callable=AsyncMock, return_value=mock_pool):
            result = await db.get_player_flag_value("p1", "nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_row(self):
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value=None)
        with patch("db.get_pool", new_callable=AsyncMock, return_value=mock_pool):
            result = await db.get_player_flag_value("p1", "any_flag")
        assert result is None


class TestGetScene:
    SAMPLE_SCENE = {
        "id": "scene_road_to_millhaven",
        "name": "Road to Millhaven",
        "type": "quest",
        "region_type": "wilderness",
        "instructions": "Travel narration.",
        "beats": [],
    }

    @pytest.mark.asyncio
    async def test_returns_scene_from_db(self):
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value={"data": json.dumps(self.SAMPLE_SCENE)})
        with patch("db.get_pool", new_callable=AsyncMock, return_value=mock_pool):
            with patch("db._cache_get", new_callable=AsyncMock, return_value=None):
                with patch("db._cache_set", new_callable=AsyncMock):
                    result = await db.get_scene("scene_road_to_millhaven")
        assert result is not None
        assert result["id"] == "scene_road_to_millhaven"
        assert result["region_type"] == "wilderness"

    @pytest.mark.asyncio
    async def test_returns_cached_data(self):
        with patch("db._cache_get", new_callable=AsyncMock, return_value=json.dumps(self.SAMPLE_SCENE)):
            result = await db.get_scene("scene_road_to_millhaven")
        assert result is not None
        assert result["name"] == "Road to Millhaven"

    @pytest.mark.asyncio
    async def test_returns_none_if_not_found(self):
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value=None)
        with patch("db.get_pool", new_callable=AsyncMock, return_value=mock_pool):
            with patch("db._cache_get", new_callable=AsyncMock, return_value=None):
                result = await db.get_scene("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_uses_provided_connection(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={"val": "42"})
        result = await db.get_player_flag_value("p1", "score", conn=mock_conn)
        assert result == 42
        mock_conn.fetchrow.assert_awaited_once()
