"""Tests for scene queries, batch scene fetch, and session-init portraits."""

import json
from unittest.mock import AsyncMock, patch

import pytest

import db
import db_content_queries
import db_queries
import db_session_queries


async def _session_init(player: dict) -> dict:
    mock_pool = AsyncMock()
    mock_pool.fetchrow = AsyncMock(return_value={"data": json.dumps(player)})
    mock_pool.fetch = AsyncMock(return_value=[])
    with patch("db.get_pool", return_value=mock_pool):
        with patch("db_content_queries.get_location", return_value={"id": "tavern", "name": "Tavern"}):
            return await db_session_queries.get_session_init_payload("p1")


class TestSessionInitPortraits:
    """AC5: get_session_init_payload is the producer of the companion's identity (constraint 6)
    — nothing shipped a companion name to the client before this."""

    @pytest.mark.asyncio
    async def test_session_init_includes_portraits(self):
        result = await _session_init({"name": "Test", "class": "mage", "location_id": "tavern"})

        assert "portraits" in result
        assert "companion" in result["portraits"]
        assert "npcs" in result["portraits"]
        assert "primary" in result["portraits"]["companion"]
        assert "alert" in result["portraits"]["companion"]
        # Verify NPC portrait URLs are present
        assert "Guildmaster Torin" in result["portraits"]["npcs"]
        assert result["portraits"]["npcs"]["Guildmaster Torin"].startswith("/api/assets/images/npc_")

    @pytest.mark.asyncio
    async def test_payload_names_the_assigned_companion(self):
        result = await _session_init({"name": "Test", "class": "warrior", "location_id": "tavern"})
        assert result["companion"] == {
            "id": "companion_lira",
            "name": "Lira",
            "voice_id": "COMPANION_LIRA",
        }

    @pytest.mark.asyncio
    async def test_companion_without_a_generated_asset_set_yields_an_explicit_null(self):
        """Lira/Tam/Sable have no generated portrait assets. An explicit null, not Kael's face,
        and not a missing key the client can fall through on."""
        result = await _session_init({"name": "Test", "class": "warrior", "location_id": "tavern"})
        assert result["portraits"]["companion"] is None
        assert result["portraits"]["npcs"]

    @pytest.mark.asyncio
    async def test_kael_player_still_gets_kaels_portraits(self):
        result = await _session_init({"name": "Test", "class": "mage", "location_id": "tavern"})
        assert result["companion"]["id"] == "companion_kael"
        assert result["portraits"]["companion"]["primary"].endswith("companion_kael_primary")

    @pytest.mark.asyncio
    async def test_a_player_row_with_no_resolvable_class_still_yields_a_payload(self):
        """A class that matches no companion is already fatal at session start
        (test_unassignable_archetype_fails_loud_instead_of_defaulting_to_kael), so raising HERE
        buys nothing and costs the whole payload — this builder's caller wraps it in a logging
        except, so a raise loses the character sheet, inventory, quests and map too. The
        companion is null and the resolution failure is logged; the branch ships pinned."""
        result = await _session_init({"name": "Test", "location_id": "tavern"})
        assert result["companion"] is None
        assert result["portraits"]["companion"] is None
        assert result["portraits"]["npcs"]
        assert result["character"]["name"] == "Test"

    def test_build_portraits_produces_valid_urls(self):
        """_build_portraits keys the companion entry on the assigned companion; a companion
        with no generated asset set, and an unresolved one, both get an explicit null."""
        result = db._build_portraits("companion_kael")
        assert result["companion"]["primary"].startswith("/api/assets/images/companion_")
        assert result["companion"]["alert"].startswith("/api/assets/images/companion_")
        for url in result["npcs"].values():
            assert url.startswith("/api/assets/images/npc_")

        assert db._build_portraits("companion_lira")["companion"] is None
        assert db._build_portraits(None)["companion"] is None

    def test_resolve_player_companion_id_is_the_single_resolution_point(self):
        assert db.resolve_player_companion_id({"class": "warrior"}) == "companion_lira"
        assert db.resolve_player_companion_id({"class": "mage"}) == "companion_kael"
        assert db.resolve_player_companion_id({"class": "necromancer"}) is None
        assert db.resolve_player_companion_id({"name": "no class"}) is None
        assert db.resolve_player_companion_id(None) is None


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
