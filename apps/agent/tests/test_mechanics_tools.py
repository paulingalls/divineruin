"""Integration tests for mechanics tools (mocked DB + room)."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError

import event_types as E
from check_tools import _mark_skill_breakthrough_impl
from environment_tools import play_sound
from session_data import SessionData

# Exported for reuse by test_hybrid_counter (skill-check path); no longer used in-file
# after the request_attack tests were removed (story-009).
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
    "equipment": {
        "main_hand": {
            "name": "Longsword",
            "damage": "1d8",
            "damage_type": "slashing",
            "properties": [],
        }
    },
    "hp": {"current": 25, "max": 25},
    "ac": 14,
}


def _make_context(player_id="player_1", location_id="accord_guild_hall", room=None):
    ctx = MagicMock()
    ctx.userdata = SessionData(player_id=player_id, location_id=location_id, room=room)
    return ctx


def _make_mock_room():
    room = MagicMock()
    room.local_participant = MagicMock()
    room.local_participant.publish_data = AsyncMock()
    return room


# --- mark_skill_breakthrough ---


class TestMarkSkillBreakthrough:
    @pytest.mark.asyncio
    async def test_mark_skill_breakthrough_sets_flag(self):
        mock_mutations = MagicMock()
        mock_mutations.mark_narrative_moment = AsyncMock()
        ctx = _make_context()
        result = json.loads(await _mark_skill_breakthrough_impl(ctx, skill="athletics", mutations=mock_mutations))
        assert result["status"] == "ok"
        assert result["skill"] == "athletics"
        mock_mutations.mark_narrative_moment.assert_awaited_once_with("player_1", "athletics")

    @pytest.mark.asyncio
    async def test_mark_skill_breakthrough_invalid_skill(self):
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _mark_skill_breakthrough_impl(ctx, skill="flying")


# --- play_sound ---


class TestPlaySound:
    @pytest.mark.asyncio
    async def test_returns_confirmation(self):
        ctx = _make_context()
        result = json.loads(await play_sound._func(ctx, sound_name="spell_cast"))
        assert result["status"] == "playing"
        assert result["sound_name"] == "spell_cast"

    @pytest.mark.asyncio
    async def test_publishes_event(self):
        room = _make_mock_room()
        ctx = _make_context(room=room)
        await play_sound._func(ctx, sound_name="sword_clash")
        room.local_participant.publish_data.assert_called_once()
        call_data = json.loads(room.local_participant.publish_data.call_args[0][0])
        assert call_data["type"] == E.PLAY_SOUND
        assert call_data["sound_name"] == "sword_clash"
