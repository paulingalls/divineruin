"""Integration tests for mechanics tools (mocked DB + room)."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError

from check_tools import _mark_skill_breakthrough_impl
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


# Exported for reuse by test_hybrid_counter (skill-check path).
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
