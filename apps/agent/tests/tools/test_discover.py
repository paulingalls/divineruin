"""Tests for discover_hidden_element: skill-check discovery, gating, and event payloads."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents.llm import ToolError

from check_tools import _discover_hidden_element_impl
from tools._helpers import _make_context

LOCATION_WITH_HIDDEN = {
    "id": "test_location",
    "name": "Test Location",
    "description": "A room.",
    "atmosphere": "plain",
    "key_features": [],
    "hidden_elements": [
        {
            "id": "secret_door",
            "discover_skill": "perception",
            "dc": 12,
            "description": "A hidden passage behind the bookshelf",
        }
    ],
    "exits": {},
    "tags": [],
    "conditions": {},
}

DISCOVER_PLAYER = {
    "player_id": "player_1",
    "name": "Kael",
    "class": "warrior",
    "level": 1,
    "attributes": {
        "strength": 14,
        "dexterity": 12,
        "constitution": 13,
        "intelligence": 10,
        "wisdom": 16,
        "charisma": 8,
    },
    "proficiencies": ["perception", "athletics"],
    "hp": {"current": 25, "max": 25},
    "ac": 14,
    "equipment": {},
}


def _make_discover_mocks(location=LOCATION_WITH_HIDDEN, player=DISCOVER_PLAYER):
    """Create mock content, queries, and mutations for discover_hidden_element tests."""
    mock_content = MagicMock()
    mock_content.get_location = AsyncMock(return_value=location)
    mock_queries = MagicMock()
    mock_queries.get_player = AsyncMock(return_value=player)
    mock_mutations = MagicMock()
    mock_mutations.set_player_flag = AsyncMock()
    return mock_content, mock_queries, mock_mutations


class TestDiscoverHiddenElement:
    @pytest.mark.asyncio
    @patch("check_tools.publish_game_event", new_callable=AsyncMock)
    async def test_successful_discovery(self, mock_event):
        mock_content, mock_queries, mock_mutations = _make_discover_mocks()
        ctx = _make_context(location_id="test_location")

        with patch("check_resolution.dice_roll") as mock_dice:
            from dice import DiceResult

            mock_dice.return_value = DiceResult(notation="d20", rolls=[15], dropped=[], total=15)
            result = json.loads(
                await _discover_hidden_element_impl(
                    ctx, element_id="secret_door", content=mock_content, queries=mock_queries, mutations=mock_mutations
                )
            )

        assert result["outcome"] == "discovered"
        assert "hidden passage" in result["description"]
        assert result["element_id"] == "secret_door"
        mock_mutations.set_player_flag.assert_called_once_with("player_1", "secret_door.discovered", True)

    @pytest.mark.asyncio
    @patch("check_tools.publish_game_event", new_callable=AsyncMock)
    async def test_failed_discovery(self, mock_event):
        mock_content, mock_queries, mock_mutations = _make_discover_mocks()
        ctx = _make_context(location_id="test_location")

        with patch("check_resolution.dice_roll") as mock_dice:
            from dice import DiceResult

            mock_dice.return_value = DiceResult(notation="d20", rolls=[3], dropped=[], total=3)
            result = json.loads(
                await _discover_hidden_element_impl(
                    ctx, element_id="secret_door", content=mock_content, queries=mock_queries, mutations=mock_mutations
                )
            )

        assert result["outcome"] == "not_found"
        assert "description" not in result

    @pytest.mark.asyncio
    async def test_invalid_element_id(self):
        mock_content = MagicMock()
        mock_content.get_location = AsyncMock(return_value=LOCATION_WITH_HIDDEN)
        ctx = _make_context(location_id="test_location")
        with pytest.raises(ToolError, match="No hidden element"):
            await _discover_hidden_element_impl(ctx, element_id="nonexistent", content=mock_content)

    @pytest.mark.asyncio
    async def test_location_not_found(self):
        mock_content = MagicMock()
        mock_content.get_location = AsyncMock(return_value=None)
        ctx = _make_context(location_id="nowhere")
        with pytest.raises(ToolError, match="not found"):
            await _discover_hidden_element_impl(ctx, element_id="secret_door", content=mock_content)

    @pytest.mark.asyncio
    @patch("check_tools.publish_game_event", new_callable=AsyncMock)
    async def test_blocks_repeated_attempt(self, mock_event):
        mock_content, mock_queries, mock_mutations = _make_discover_mocks()
        ctx = _make_context(location_id="test_location")

        with patch("check_resolution.dice_roll") as mock_dice:
            from dice import DiceResult

            mock_dice.return_value = DiceResult(notation="d20", rolls=[3], dropped=[], total=3)
            await _discover_hidden_element_impl(
                ctx, element_id="secret_door", content=mock_content, queries=mock_queries, mutations=mock_mutations
            )

        with pytest.raises(ToolError, match="Already searched"):
            await _discover_hidden_element_impl(
                ctx, element_id="secret_door", content=mock_content, queries=mock_queries, mutations=mock_mutations
            )

    @pytest.mark.asyncio
    @patch("check_tools.publish_game_event", new_callable=AsyncMock)
    async def test_dice_roll_event_has_no_dc(self, mock_event):
        """DC should not be included in the client-facing dice_roll event."""
        mock_content, mock_queries, mock_mutations = _make_discover_mocks()
        ctx = _make_context(location_id="test_location")

        with patch("check_resolution.dice_roll") as mock_dice:
            from dice import DiceResult

            mock_dice.return_value = DiceResult(notation="d20", rolls=[15], dropped=[], total=15)
            await _discover_hidden_element_impl(
                ctx, element_id="secret_door", content=mock_content, queries=mock_queries, mutations=mock_mutations
            )

        event_payload = mock_event.call_args[0][2]
        assert "dc" not in event_payload
