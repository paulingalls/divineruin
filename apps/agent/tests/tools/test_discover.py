"""Tests for check(mode="discover") — §7 skill/target discovery.

check(skill, target) takes a VISIBLE target; the hidden element's id is the Resolve's
OUTPUT on success, never an input. M5 scopes the location's hidden_elements room-wide by
matching discover_skill (the §7 fallback). Covers success/failure, skill-scoping,
repeat-block on (skill:target), the dc-less event, and the lowest-DC tie-break.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents.llm import ToolError

from check_discovery import _check_discover_impl
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

LOCATION_TWO_SECRETS = {
    **LOCATION_WITH_HIDDEN,
    "hidden_elements": [
        {"id": "hard_secret", "discover_skill": "perception", "dc": 15, "description": "A hard find"},
        {"id": "easy_secret", "discover_skill": "perception", "dc": 10, "description": "An easy find"},
    ],
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
    mock_content = MagicMock()
    mock_content.get_location = AsyncMock(return_value=location)
    mock_queries = MagicMock()
    mock_queries.get_player = AsyncMock(return_value=player)
    mock_mutations = MagicMock()
    mock_mutations.set_player_flag = AsyncMock()
    return mock_content, mock_queries, mock_mutations


def _roll(total):
    from dice import DiceResult

    return DiceResult(notation="d20", rolls=[total], dropped=[], total=total)


class TestCheckDiscover:
    @pytest.mark.asyncio
    @patch("check_discovery.publish_game_event", new_callable=AsyncMock)
    async def test_successful_discovery(self, mock_event):
        content, queries, mutations = _make_discover_mocks()
        ctx = _make_context(location_id="test_location")
        with patch("check_resolution.dice_roll", return_value=_roll(15)):
            result = json.loads(
                await _check_discover_impl(
                    ctx, "perception", "bookshelf", content=content, queries=queries, mutations=mutations
                )
            )
        assert result["outcome"] == "discovered"
        assert "hidden passage" in result["description"]
        # The element id surfaces in the RESPONSE only (an output, never an input).
        assert result["element_id"] == "secret_door"
        assert result["target"] == "bookshelf"
        mutations.set_player_flag.assert_called_once_with("player_1", "secret_door.discovered", True)

    @pytest.mark.asyncio
    @patch("check_discovery.publish_game_event", new_callable=AsyncMock)
    async def test_failed_discovery(self, mock_event):
        content, queries, mutations = _make_discover_mocks()
        ctx = _make_context(location_id="test_location")
        with patch("check_resolution.dice_roll", return_value=_roll(3)):
            result = json.loads(
                await _check_discover_impl(
                    ctx, "perception", "bookshelf", content=content, queries=queries, mutations=mutations
                )
            )
        assert result["outcome"] == "not_found"
        assert "description" not in result
        mutations.set_player_flag.assert_not_called()

    @pytest.mark.asyncio
    @patch("check_discovery.publish_game_event", new_callable=AsyncMock)
    async def test_no_matching_skill_returns_not_found(self, mock_event):
        # A skill with no scoped hidden element is a valid "found nothing", not an error.
        content, queries, mutations = _make_discover_mocks()
        ctx = _make_context(location_id="test_location")
        result = json.loads(
            await _check_discover_impl(
                ctx, "arcana", "bookshelf", content=content, queries=queries, mutations=mutations
            )
        )
        assert result["outcome"] == "not_found"
        mock_event.assert_not_called()

    @pytest.mark.asyncio
    @patch("check_discovery.publish_game_event", new_callable=AsyncMock)
    async def test_no_candidate_search_is_retryable(self, mock_event):
        # A search that finds NO matching element never rolled, so it must not block a
        # retry — re-searching returns not_found again, not "Already searched".
        content, queries, mutations = _make_discover_mocks()
        ctx = _make_context(location_id="test_location")
        first = json.loads(
            await _check_discover_impl(
                ctx, "arcana", "bookshelf", content=content, queries=queries, mutations=mutations
            )
        )
        second = json.loads(
            await _check_discover_impl(
                ctx, "arcana", "bookshelf", content=content, queries=queries, mutations=mutations
            )
        )
        assert first["outcome"] == "not_found"
        assert second["outcome"] == "not_found"
        mock_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_skill_raises(self):
        content, queries, _ = _make_discover_mocks()
        ctx = _make_context(location_id="test_location")
        with pytest.raises(ToolError, match="skill"):
            await _check_discover_impl(ctx, "flying", "bookshelf", content=content, queries=queries)

    @pytest.mark.asyncio
    async def test_location_not_found(self):
        content = MagicMock()
        content.get_location = AsyncMock(return_value=None)
        ctx = _make_context(location_id="nowhere")
        with pytest.raises(ToolError, match="not found"):
            await _check_discover_impl(ctx, "perception", "bookshelf", content=content)

    @pytest.mark.asyncio
    @patch("check_discovery.publish_game_event", new_callable=AsyncMock)
    async def test_blocks_repeated_attempt(self, mock_event):
        content, queries, mutations = _make_discover_mocks()
        ctx = _make_context(location_id="test_location")
        with patch("check_resolution.dice_roll", return_value=_roll(3)):
            await _check_discover_impl(
                ctx, "perception", "bookshelf", content=content, queries=queries, mutations=mutations
            )
        # Re-searching the same target with the same approach this session is blocked.
        with pytest.raises(ToolError, match="Already searched"):
            await _check_discover_impl(
                ctx, "perception", "bookshelf", content=content, queries=queries, mutations=mutations
            )

    @pytest.mark.asyncio
    @patch("check_discovery.publish_game_event", new_callable=AsyncMock)
    async def test_dice_roll_event_has_no_dc(self, mock_event):
        content, queries, mutations = _make_discover_mocks()
        ctx = _make_context(location_id="test_location")
        with patch("check_resolution.dice_roll", return_value=_roll(15)):
            await _check_discover_impl(
                ctx, "perception", "bookshelf", content=content, queries=queries, mutations=mutations
            )
        event_payload = mock_event.call_args[0][2]
        assert "dc" not in event_payload

    @pytest.mark.asyncio
    @patch("check_discovery.publish_game_event", new_callable=AsyncMock)
    async def test_multi_element_tiebreak_lowest_dc(self, mock_event):
        # Two perception secrets in the room — the lowest-DC one surfaces first.
        content, queries, mutations = _make_discover_mocks(location=LOCATION_TWO_SECRETS)
        ctx = _make_context(location_id="test_location")
        with patch("check_resolution.dice_roll", return_value=_roll(12)):
            result = json.loads(
                await _check_discover_impl(
                    ctx, "perception", "bookshelf", content=content, queries=queries, mutations=mutations
                )
            )
        assert result["outcome"] == "discovered"
        assert result["element_id"] == "easy_secret"
        mutations.set_player_flag.assert_called_once_with("player_1", "easy_secret.discovered", True)
