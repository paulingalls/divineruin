"""Tests for the query_info tools: location, npc, lore, inventory, and dispatch."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents.llm import ToolError

from query_tools import (
    _query_info_impl,
    _query_inventory_impl,
    _query_location_impl,
    _query_lore_impl,
    _query_npc_impl,
)
from tools._helpers import SAMPLE_LOCATION, _make_context

SAMPLE_NPC = {
    "id": "guildmaster_torin",
    "name": "Guildmaster Torin",
    "role": "guild hall master",
    "personality": ["pragmatic"],
    "speech_style": "direct, wastes no words",
    "mannerisms": ["drums fingers on desk"],
    "appearance": "broad-shouldered",
    "default_disposition": "neutral",
    "knowledge": {
        "free": ["general guild operations"],
        "disposition >= friendly": ["he sent scouts north"],
        "disposition >= trusted": ["he suspects the temple"],
    },
    "secrets": ["his missing scout is personal"],
    "voice_notes": "deep baritone",
}


class TestQueryLocation:
    @pytest.mark.asyncio
    async def test_returns_location(self):
        mock_content = MagicMock()
        mock_content.get_location = AsyncMock(return_value=SAMPLE_LOCATION)
        ctx = _make_context()
        result = json.loads(await _query_location_impl(ctx, location_id="accord_guild_hall", content=mock_content))
        assert result["name"] == "Guild Hall"
        assert "dc" not in json.dumps(result["hidden_elements"])
        assert "discover_skill" not in json.dumps(result["hidden_elements"])

    @pytest.mark.asyncio
    async def test_missing_location(self):
        mock_content = MagicMock()
        mock_content.get_location = AsyncMock(return_value=None)
        ctx = _make_context()
        with pytest.raises(ToolError, match="not found"):
            await _query_location_impl(ctx, location_id="nonexistent", content=mock_content)


class TestQueryNpc:
    @pytest.mark.asyncio
    async def test_returns_npc_neutral(self):
        mock_content = MagicMock()
        mock_content.get_npc = AsyncMock(return_value=SAMPLE_NPC)
        mock_queries = MagicMock()
        mock_queries.get_npc_disposition = AsyncMock(return_value=None)  # falls back to default_disposition
        ctx = _make_context()
        result = json.loads(
            await _query_npc_impl(ctx, npc_id="guildmaster_torin", queries=mock_queries, content=mock_content)
        )
        assert result["name"] == "Guildmaster Torin"
        assert result["disposition"] == "neutral"
        assert "general guild operations" in result["knowledge"]
        assert "he sent scouts north" not in result["knowledge"]
        assert "secrets" not in result

    @pytest.mark.asyncio
    async def test_friendly_reveals_more(self):
        mock_content = MagicMock()
        mock_content.get_npc = AsyncMock(return_value=SAMPLE_NPC)
        mock_queries = MagicMock()
        mock_queries.get_npc_disposition = AsyncMock(return_value="friendly")
        ctx = _make_context()
        result = json.loads(
            await _query_npc_impl(ctx, npc_id="guildmaster_torin", queries=mock_queries, content=mock_content)
        )
        assert result["disposition"] == "friendly"
        assert "he sent scouts north" in result["knowledge"]
        assert "he suspects the temple" not in result["knowledge"]

    @pytest.mark.asyncio
    async def test_trusted_reveals_all(self):
        mock_content = MagicMock()
        mock_content.get_npc = AsyncMock(return_value=SAMPLE_NPC)
        mock_queries = MagicMock()
        mock_queries.get_npc_disposition = AsyncMock(return_value="trusted")
        ctx = _make_context()
        result = json.loads(
            await _query_npc_impl(ctx, npc_id="guildmaster_torin", queries=mock_queries, content=mock_content)
        )
        assert "he suspects the temple" in result["knowledge"]

    @pytest.mark.asyncio
    async def test_missing_npc(self):
        mock_content = MagicMock()
        mock_content.get_npc = AsyncMock(return_value=None)
        ctx = _make_context()
        with pytest.raises(ToolError, match="not found"):
            await _query_npc_impl(ctx, npc_id="nobody", content=mock_content)


class TestQueryLore:
    @pytest.mark.asyncio
    async def test_returns_entries(self):
        mock_content = MagicMock()
        mock_content.search_lore = AsyncMock(
            return_value=[{"title": "The Hollow", "category": "cosmology", "content": "Bad stuff.", "tags": ["hollow"]}]
        )
        ctx = _make_context()
        result = json.loads(await _query_lore_impl(ctx, topic="hollow", content=mock_content))
        assert len(result["entries"]) == 1
        assert result["entries"][0]["title"] == "The Hollow"

    @pytest.mark.asyncio
    async def test_no_matches(self):
        mock_content = MagicMock()
        mock_content.search_lore = AsyncMock(return_value=[])
        ctx = _make_context()
        result = json.loads(await _query_lore_impl(ctx, topic="nonexistent", content=mock_content))
        assert "note" in result


class TestQueryInventory:
    @pytest.mark.asyncio
    async def test_returns_items(self):
        mock_queries = MagicMock()
        mock_queries.get_player_inventory = AsyncMock(
            return_value=[
                {
                    "name": "Sealed Research Tablet",
                    "type": "quest_item",
                    "description": "A warm stone tablet.",
                    "rarity": "rare",
                    "effects": [],
                    "lore": "Research notes from an Aelindran outpost.",
                }
            ]
        )
        ctx = _make_context()
        result = json.loads(await _query_inventory_impl(ctx, queries=mock_queries))
        assert len(result["items"]) == 1
        assert result["items"][0]["name"] == "Sealed Research Tablet"
        mock_queries.get_player_inventory.assert_awaited_once_with("player_1")

    @pytest.mark.asyncio
    async def test_empty_inventory(self):
        mock_queries = MagicMock()
        mock_queries.get_player_inventory = AsyncMock(return_value=[])
        ctx = _make_context()
        result = json.loads(await _query_inventory_impl(ctx, queries=mock_queries))
        assert "note" in result


class TestQueryInfo:
    """query_info dispatches by kind to the unchanged per-kind impls."""

    @pytest.mark.asyncio
    async def test_routes_location(self):
        ctx = _make_context()
        with patch("query_tools._query_location_impl", new_callable=AsyncMock, return_value='{"k":"loc"}') as m:
            result = await _query_info_impl(ctx, "location", "accord_guild_hall")
        m.assert_awaited_once_with(ctx, "accord_guild_hall")
        assert result == '{"k":"loc"}'

    @pytest.mark.asyncio
    async def test_routes_npc(self):
        ctx = _make_context()
        with patch("query_tools._query_npc_impl", new_callable=AsyncMock, return_value='{"k":"npc"}') as m:
            result = await _query_info_impl(ctx, "npc", "guildmaster_torin")
        m.assert_awaited_once_with(ctx, "guildmaster_torin")
        assert result == '{"k":"npc"}'

    @pytest.mark.asyncio
    async def test_routes_lore_with_topic(self):
        ctx = _make_context()
        with patch("query_tools._query_lore_impl", new_callable=AsyncMock, return_value='{"k":"lore"}') as m:
            result = await _query_info_impl(ctx, "lore", "the Hollow")
        m.assert_awaited_once_with(ctx, "the Hollow")
        assert result == '{"k":"lore"}'

    @pytest.mark.asyncio
    async def test_routes_inventory_without_target(self):
        ctx = _make_context()
        with patch("query_tools._query_inventory_impl", new_callable=AsyncMock, return_value='{"k":"inv"}') as m:
            result = await _query_info_impl(ctx, "inventory", None)
        m.assert_awaited_once_with(ctx)
        assert result == '{"k":"inv"}'

    @pytest.mark.asyncio
    @pytest.mark.parametrize("kind", ["location", "npc", "lore"])
    async def test_missing_target_id_raises(self, kind):
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _query_info_impl(ctx, kind, None)
