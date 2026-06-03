"""Tests for scene queries, batch scene fetch, and session-init portraits."""

import json
from unittest.mock import AsyncMock, patch

import pytest

import db
import db_content_queries
import db_queries


class TestSessionInitPortraits:
    """Test that get_session_init_payload includes portraits."""

    @pytest.mark.asyncio
    async def test_session_init_includes_portraits(self):
        """get_session_init_payload should include portraits dict."""
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value={"data": json.dumps({"name": "Test", "location_id": "tavern"})})
        mock_pool.fetch = AsyncMock(return_value=[])

        with patch("db.get_pool", return_value=mock_pool):
            with patch("db_content_queries.get_location", return_value={"id": "tavern", "name": "Tavern"}):
                result = await db_queries.get_session_init_payload("p1")

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
                    result = await db_content_queries.get_scene("scene_road_to_millhaven")
        assert result is not None
        assert result["id"] == "scene_road_to_millhaven"
        assert result["region_type"] == "wilderness"

    @pytest.mark.asyncio
    async def test_returns_cached_data(self):
        with patch("db._cache_get", new_callable=AsyncMock, return_value=json.dumps(self.SAMPLE_SCENE)):
            result = await db_content_queries.get_scene("scene_road_to_millhaven")
        assert result is not None
        assert result["name"] == "Road to Millhaven"

    @pytest.mark.asyncio
    async def test_returns_none_if_not_found(self):
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value=None)
        with patch("db.get_pool", new_callable=AsyncMock, return_value=mock_pool):
            with patch("db._cache_get", new_callable=AsyncMock, return_value=None):
                result = await db_content_queries.get_scene("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_uses_provided_connection(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={"val": "42"})
        result = await db_queries.get_player_flag_value("p1", "score", conn=mock_conn)
        assert result == 42
        mock_conn.fetchrow.assert_awaited_once()


class TestGetScenesBatch:
    SCENE_A = {"id": "scene_a", "name": "A", "type": "quest", "region_type": "city", "instructions": "x", "beats": []}
    SCENE_B = {
        "id": "scene_b",
        "name": "B",
        "type": "quest",
        "region_type": "wilderness",
        "instructions": "y",
        "beats": [],
    }

    @pytest.mark.asyncio
    async def test_returns_all_scenes_from_db(self):
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(
            return_value=[
                {"id": "scene_a", "data": json.dumps(self.SCENE_A)},
                {"id": "scene_b", "data": json.dumps(self.SCENE_B)},
            ]
        )
        with patch("db.get_pool", new_callable=AsyncMock, return_value=mock_pool):
            with patch("db._cache_get", new_callable=AsyncMock, return_value=None):
                with patch("db._cache_set", new_callable=AsyncMock):
                    result = await db_content_queries.get_scenes_batch(["scene_a", "scene_b"])
        assert len(result) == 2
        assert result["scene_a"]["name"] == "A"
        assert result["scene_b"]["name"] == "B"

    @pytest.mark.asyncio
    async def test_returns_cached_scenes(self):
        async def cache_get(key):
            if key == "scene:scene_a":
                return json.dumps(self.SCENE_A)
            return None

        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[{"id": "scene_b", "data": json.dumps(self.SCENE_B)}])
        with patch("db.get_pool", new_callable=AsyncMock, return_value=mock_pool):
            with patch("db._cache_get", new_callable=AsyncMock, side_effect=cache_get):
                with patch("db._cache_set", new_callable=AsyncMock):
                    result = await db_content_queries.get_scenes_batch(["scene_a", "scene_b"])
        assert len(result) == 2
        # scene_a from cache, scene_b from DB
        assert result["scene_a"]["name"] == "A"
        assert result["scene_b"]["name"] == "B"

    @pytest.mark.asyncio
    async def test_skips_missing_scenes(self):
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[{"id": "scene_a", "data": json.dumps(self.SCENE_A)}])
        with patch("db.get_pool", new_callable=AsyncMock, return_value=mock_pool):
            with patch("db._cache_get", new_callable=AsyncMock, return_value=None):
                with patch("db._cache_set", new_callable=AsyncMock):
                    result = await db_content_queries.get_scenes_batch(["scene_a", "nonexistent"])
        assert len(result) == 1
        assert "scene_a" in result
        assert "nonexistent" not in result

    @pytest.mark.asyncio
    async def test_empty_ids_returns_empty(self):
        result = await db_content_queries.get_scenes_batch([])
        assert result == {}
