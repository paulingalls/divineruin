"""Tests for enter_location scene assembly and time-of-day overrides."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError

from query_tools import _query_location_impl
from scene_tools import _enter_location_impl
from tools._helpers import SAMPLE_LOCATION, _make_context

SAMPLE_NPC_RAW = {
    "id": "guildmaster_torin",
    "name": "Guildmaster Torin",
    "role": "guild hall master",
    "default_disposition": "neutral",
    "voice_notes": "deep baritone",
    "schedule": {"07:00-22:00": "accord_guild_hall"},
}

SAMPLE_TARGET = {
    "npc_id": "guild_training_dummy",
    "name": "Training Dummy",
    "location": "accord_guild_hall",
    "ac": 10,
    "hp": {"current": 50, "max": 50},
    "description": "A battered wooden post.",
}

SAMPLE_PLAYER = {
    "player_id": "player_1",
    "name": "Kael",
    "class": "warrior",
    "level": 1,
    "hp": {"current": 25, "max": 25},
    "ac": 14,
    "equipment": {
        "main_hand": {
            "name": "Longsword",
            "damage": "1d8",
            "damage_type": "slashing",
            "properties": [],
        }
    },
}


def _make_scene_mocks(location=SAMPLE_LOCATION, npcs=None, dispositions=None, targets=None, player=SAMPLE_PLAYER):
    """Create mock content and queries modules for scene/enter_location tests."""
    mock_content = MagicMock()
    mock_content.get_location = AsyncMock(return_value=location)
    mock_queries = MagicMock()
    mock_queries.get_npcs_at_location = AsyncMock(return_value=npcs if npcs is not None else [])
    mock_queries.get_npc_dispositions = AsyncMock(return_value=dispositions if dispositions is not None else {})
    mock_queries.get_targets_at_location = AsyncMock(return_value=targets if targets is not None else [])
    mock_queries.get_player = AsyncMock(return_value=player)
    return mock_content, mock_queries


class TestEnterLocation:
    @pytest.mark.asyncio
    async def test_returns_full_context(self):
        mock_content, mock_queries = _make_scene_mocks(
            location=SAMPLE_LOCATION,
            npcs=[SAMPLE_NPC_RAW],
            dispositions={},
            targets=[SAMPLE_TARGET],
            player=SAMPLE_PLAYER,
        )
        ctx = _make_context()
        result = json.loads(
            await _enter_location_impl(ctx, location_id="accord_guild_hall", content=mock_content, queries=mock_queries)
        )

        assert result["location"]["name"] == "Guild Hall"
        assert len(result["npcs"]) == 1
        assert result["npcs"][0]["id"] == "guildmaster_torin"
        assert result["npcs"][0]["disposition"] == "neutral"
        assert len(result["targets"]) == 1
        assert result["targets"][0]["id"] == "guild_training_dummy"
        assert result["targets"][0]["ac"] == 10
        assert result["player"]["name"] == "Kael"
        assert result["player"]["weapon"] == "Longsword"

    @pytest.mark.asyncio
    async def test_missing_location(self):
        mock_content = MagicMock()
        mock_content.get_location = AsyncMock(return_value=None)
        ctx = _make_context()
        with pytest.raises(ToolError, match="not found"):
            await _enter_location_impl(ctx, location_id="nowhere", content=mock_content)

    @pytest.mark.asyncio
    async def test_empty_npcs_and_targets(self):
        mock_content, mock_queries = _make_scene_mocks(
            location=SAMPLE_LOCATION,
            npcs=[],
            targets=[],
            player=SAMPLE_PLAYER,
        )
        ctx = _make_context()
        result = json.loads(
            await _enter_location_impl(ctx, location_id="accord_guild_hall", content=mock_content, queries=mock_queries)
        )

        assert result["npcs"] == []
        assert result["targets"] == []
        assert result["location"]["name"] == "Guild Hall"


NIGHT_LOCATION = {
    "id": "accord_market_square",
    "name": "Market Square",
    "description": "Sunny market",
    "atmosphere": "busy",
    "key_features": ["a fountain"],
    "hidden_elements": [],
    "exits": {"north": {"destination": "accord_guild_hall"}},
    "tags": ["market"],
    "conditions": {
        "time_night": {
            "description_override": "Dark empty market",
            "atmosphere": "quiet, reflective",
        }
    },
}


class TestNightConditionsInTools:
    @pytest.mark.asyncio
    async def test_build_scene_applies_night(self):
        mock_content, mock_queries = _make_scene_mocks(
            location=NIGHT_LOCATION,
            npcs=[],
            targets=[],
            player=SAMPLE_PLAYER,
        )
        ctx = _make_context()
        ctx.userdata.world_time = "night"
        result = json.loads(
            await _enter_location_impl(
                ctx, location_id="accord_market_square", content=mock_content, queries=mock_queries
            )
        )
        assert result["location"]["description"] == "Dark empty market"
        assert result["location"]["atmosphere"] == "quiet, reflective"

    @pytest.mark.asyncio
    async def test_build_scene_day_no_override(self):
        mock_content, mock_queries = _make_scene_mocks(
            location=NIGHT_LOCATION,
            npcs=[],
            targets=[],
            player=SAMPLE_PLAYER,
        )
        ctx = _make_context()
        ctx.userdata.world_time = "day"
        result = json.loads(
            await _enter_location_impl(
                ctx, location_id="accord_market_square", content=mock_content, queries=mock_queries
            )
        )
        assert result["location"]["description"] == "Sunny market"

    @pytest.mark.asyncio
    async def test_query_location_applies_night(self):
        mock_content = MagicMock()
        mock_content.get_location = AsyncMock(return_value=NIGHT_LOCATION)
        ctx = _make_context()
        ctx.userdata.world_time = "night"
        result = json.loads(await _query_location_impl(ctx, location_id="accord_market_square", content=mock_content))
        assert result["description"] == "Dark empty market"

    @pytest.mark.asyncio
    async def test_query_location_day_no_override(self):
        mock_content = MagicMock()
        mock_content.get_location = AsyncMock(return_value=NIGHT_LOCATION)
        ctx = _make_context()
        ctx.userdata.world_time = "day"
        result = json.loads(await _query_location_impl(ctx, location_id="accord_market_square", content=mock_content))
        assert result["description"] == "Sunny market"
