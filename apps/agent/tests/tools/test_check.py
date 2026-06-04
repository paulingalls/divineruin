"""Tests for the consolidated `check` verb — skill/save/dice modes + dispatch.

Discovery mode is covered separately in tests/tools/test_discover.py (the §7
visible-target path). These exercise the migrated request_skill_check /
request_saving_throw / roll_dice behaviors through check's sub-impls, plus the
mode dispatcher's fail-loud on an unknown mode.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError

import event_types as E
from check_tools import _check_dice_impl, _check_impl, _check_save_impl, _check_skill_impl
from session_data import SessionData

SAMPLE_PLAYER = {
    "player_id": "player_1",
    "name": "Kael",
    "class": "warrior",
    "level": 1,
    "attributes": {
        "strength": 14,
        "dexterity": 12,
        "constitution": 13,
        "intelligence": 10,
        "wisdom": 11,
        "charisma": 8,
    },
    "proficiencies": ["athletics", "stealth", "perception"],
    "saving_throw_proficiencies": ["strength", "constitution"],
    "hp": {"current": 25, "max": 25},
    "ac": 14,
}


def _make_context(room=None):
    ctx = MagicMock()
    ctx.userdata = SessionData(player_id="player_1", location_id="accord_guild_hall", room=room)
    return ctx


def _make_mock_room():
    room = MagicMock()
    room.local_participant = MagicMock()
    room.local_participant.publish_data = AsyncMock()
    return room


def _skill_mocks():
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
    queries.get_single_skill_advancement = AsyncMock(
        return_value={"tier": "untrained", "use_counter": 0, "narrative_moment_ready": False},
    )
    mutations = MagicMock()
    mutations.update_skill_advancement = AsyncMock()
    return queries, mutations


class TestCheckSkill:
    @pytest.mark.asyncio
    async def test_returns_result(self):
        queries, mutations = _skill_mocks()
        result = json.loads(
            await _check_skill_impl(
                _make_context(), "athletics", "moderate", "climbing a wall", queries=queries, mutations=mutations
            )
        )
        assert result["skill"] == "athletics"
        assert result["dc"] == 12  # moderate = 12
        assert result["outcome"] in ("success", "failure")
        assert "narrative_hint" in result

    @pytest.mark.asyncio
    async def test_unknown_skill(self):
        queries, _ = _skill_mocks()
        with pytest.raises(ToolError):
            await _check_skill_impl(_make_context(), "flying", "moderate", "trying to fly", queries=queries)

    @pytest.mark.asyncio
    async def test_invalid_difficulty(self):
        queries, _ = _skill_mocks()
        with pytest.raises(ToolError):
            await _check_skill_impl(_make_context(), "athletics", "impossible", "climbing", queries=queries)

    @pytest.mark.asyncio
    async def test_missing_player(self):
        queries = MagicMock()
        queries.get_player = AsyncMock(return_value=None)
        with pytest.raises(ToolError):
            await _check_skill_impl(_make_context(), "athletics", "moderate", "climbing", queries=queries)

    @pytest.mark.asyncio
    async def test_publishes_event(self):
        queries, mutations = _skill_mocks()
        room = _make_mock_room()
        await _check_skill_impl(
            _make_context(room=room), "stealth", "hard", "sneaking past guard", queries=queries, mutations=mutations
        )
        room.local_participant.publish_data.assert_called()
        call_data = json.loads(room.local_participant.publish_data.call_args_list[0][0][0])
        assert call_data["type"] == E.DICE_ROLL
        assert call_data["roll_type"] == "skill_check"

    @pytest.mark.asyncio
    async def test_records_skill_use(self):
        queries, mutations = _skill_mocks()
        await _check_skill_impl(
            _make_context(), "athletics", "moderate", "climbing", queries=queries, mutations=mutations
        )
        mutations.update_skill_advancement.assert_awaited_once()
        call_args = mutations.update_skill_advancement.call_args[0]
        assert call_args[0] == "player_1"
        assert call_args[1] == "athletics"


class TestCheckSave:
    @pytest.mark.asyncio
    async def test_returns_result(self):
        queries = MagicMock()
        queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
        result = json.loads(await _check_save_impl(_make_context(), "dexterity", 15, "knocked prone", queries=queries))
        assert result["save_type"] == "dexterity"
        assert result["dc"] == 15
        assert result["outcome"] in ("success", "failure")

    @pytest.mark.asyncio
    async def test_missing_player(self):
        queries = MagicMock()
        queries.get_player = AsyncMock(return_value=None)
        with pytest.raises(ToolError):
            await _check_save_impl(_make_context(), "dexterity", 15, "prone", queries=queries)

    @pytest.mark.asyncio
    async def test_invalid_save_type(self):
        queries = MagicMock()
        queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
        with pytest.raises(ToolError):
            await _check_save_impl(_make_context(), "luck", 15, "cursed", queries=queries)

    @pytest.mark.asyncio
    async def test_dc_out_of_range(self):
        queries = MagicMock()
        queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
        with pytest.raises(ToolError, match="DC"):
            await _check_save_impl(_make_context(), "dexterity", 0, "prone", queries=queries)

    @pytest.mark.asyncio
    async def test_publishes_event(self):
        queries = MagicMock()
        queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
        room = _make_mock_room()
        await _check_save_impl(_make_context(room=room), "wisdom", 12, "frightened", queries=queries)
        room.local_participant.publish_data.assert_called_once()
        call_data = json.loads(room.local_participant.publish_data.call_args[0][0])
        assert call_data["type"] == E.DICE_ROLL
        assert call_data["roll_type"] == "saving_throw"


class TestCheckDice:
    @pytest.mark.asyncio
    async def test_valid_notation(self):
        result = json.loads(await _check_dice_impl(_make_context(), "2d6"))
        assert "rolls" in result
        assert "total" in result
        assert len(result["rolls"]) == 2

    @pytest.mark.asyncio
    async def test_invalid_notation(self):
        with pytest.raises(ToolError):
            await _check_dice_impl(_make_context(), "banana")

    @pytest.mark.asyncio
    async def test_publishes_event(self):
        room = _make_mock_room()
        await _check_dice_impl(_make_context(room=room), "d20")
        room.local_participant.publish_data.assert_called_once()
        call_data = json.loads(room.local_participant.publish_data.call_args[0][0])
        assert call_data["roll_type"] == "narrative"


class TestCheckDispatch:
    @pytest.mark.asyncio
    async def test_unknown_mode_raises(self):
        with pytest.raises(ToolError, match="mode"):
            await _check_impl(_make_context(), "telepathy")

    @pytest.mark.asyncio
    async def test_skill_mode_routes_to_skill_impl(self):
        queries, mutations = _skill_mocks()
        result = json.loads(
            await _check_impl(
                _make_context(),
                "skill",
                skill="athletics",
                difficulty="moderate",
                context_description="climbing",
                queries=queries,
                mutations=mutations,
            )
        )
        assert result["skill"] == "athletics"
        assert result["dc"] == 12
