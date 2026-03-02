"""Integration tests for mechanics tools (mocked DB + room)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from session_data import SessionData
from tools import (
    request_skill_check,
    request_attack,
    request_saving_throw,
    roll_dice,
    play_sound,
)


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

SAMPLE_NPC_COMBAT = {
    "npc_id": "goblin_1",
    "name": "Goblin Scout",
    "ac": 12,
    "hp": {"current": 7, "max": 7},
}


def _make_context(player_id="player_1", location_id="accord_guild_hall", room=None):
    ctx = MagicMock()
    ctx.userdata = SessionData(
        player_id=player_id, location_id=location_id, room=room
    )
    return ctx


def _make_mock_room():
    room = MagicMock()
    room.local_participant = MagicMock()
    room.local_participant.publish_data = AsyncMock()
    return room


# --- request_skill_check ---

class TestRequestSkillCheck:
    @pytest.mark.asyncio
    @patch("tools.db.get_player", new_callable=AsyncMock)
    async def test_returns_result(self, mock_get_player):
        mock_get_player.return_value = SAMPLE_PLAYER
        ctx = _make_context()
        result = json.loads(await request_skill_check._func(
            ctx, skill="athletics", difficulty="moderate",
            context_description="climbing a wall"
        ))
        assert result["skill"] == "athletics"
        assert result["dc"] == 13
        assert result["outcome"] in ("success", "failure")
        assert "narrative_hint" in result

    @pytest.mark.asyncio
    @patch("tools.db.get_player", new_callable=AsyncMock)
    async def test_unknown_skill(self, mock_get_player):
        mock_get_player.return_value = SAMPLE_PLAYER
        ctx = _make_context()
        result = json.loads(await request_skill_check._func(
            ctx, skill="flying", difficulty="moderate",
            context_description="trying to fly"
        ))
        assert "error" in result

    @pytest.mark.asyncio
    @patch("tools.db.get_player", new_callable=AsyncMock)
    async def test_missing_player(self, mock_get_player):
        mock_get_player.return_value = None
        ctx = _make_context()
        result = json.loads(await request_skill_check._func(
            ctx, skill="athletics", difficulty="moderate",
            context_description="climbing"
        ))
        assert "error" in result

    @pytest.mark.asyncio
    @patch("tools.db.get_player", new_callable=AsyncMock)
    async def test_publishes_event(self, mock_get_player):
        mock_get_player.return_value = SAMPLE_PLAYER
        room = _make_mock_room()
        ctx = _make_context(room=room)
        await request_skill_check._func(
            ctx, skill="stealth", difficulty="hard",
            context_description="sneaking past guard"
        )
        room.local_participant.publish_data.assert_called_once()
        call_data = json.loads(room.local_participant.publish_data.call_args[0][0])
        assert call_data["type"] == "dice_roll"
        assert call_data["roll_type"] == "skill_check"


# --- request_attack ---

class TestRequestAttack:
    @pytest.mark.asyncio
    @patch("tools.db.update_npc_hp", new_callable=AsyncMock)
    @patch("tools.db.get_npc_combat_stats", new_callable=AsyncMock)
    @patch("tools.db.get_player", new_callable=AsyncMock)
    async def test_returns_result(self, mock_player, mock_npc, mock_update):
        mock_player.return_value = SAMPLE_PLAYER
        mock_npc.return_value = SAMPLE_NPC_COMBAT
        ctx = _make_context()
        result = json.loads(await request_attack._func(
            ctx, target_id="goblin_1", weapon_or_spell="Longsword"
        ))
        assert "hit" in result
        assert "damage" in result
        assert "narrative_hint" in result

    @pytest.mark.asyncio
    @patch("tools.db.get_player", new_callable=AsyncMock)
    async def test_missing_player(self, mock_player):
        mock_player.return_value = None
        ctx = _make_context()
        result = json.loads(await request_attack._func(
            ctx, target_id="goblin_1", weapon_or_spell="Longsword"
        ))
        assert "error" in result

    @pytest.mark.asyncio
    @patch("tools.db.get_player", new_callable=AsyncMock)
    async def test_missing_weapon(self, mock_player):
        mock_player.return_value = SAMPLE_PLAYER
        ctx = _make_context()
        result = json.loads(await request_attack._func(
            ctx, target_id="goblin_1", weapon_or_spell="Warhammer"
        ))
        assert "error" in result
        assert "Warhammer" in result["error"]

    @pytest.mark.asyncio
    @patch("tools.db.get_npc_combat_stats", new_callable=AsyncMock)
    @patch("tools.db.get_player", new_callable=AsyncMock)
    async def test_missing_target(self, mock_player, mock_npc):
        mock_player.return_value = SAMPLE_PLAYER
        mock_npc.return_value = None
        ctx = _make_context()
        result = json.loads(await request_attack._func(
            ctx, target_id="ghost", weapon_or_spell="Longsword"
        ))
        assert "error" in result

    @pytest.mark.asyncio
    @patch("tools.db.update_npc_hp", new_callable=AsyncMock)
    @patch("tools.db.get_npc_combat_stats", new_callable=AsyncMock)
    @patch("tools.db.get_player", new_callable=AsyncMock)
    async def test_hp_updated_on_hit(self, mock_player, mock_npc, mock_update):
        mock_player.return_value = SAMPLE_PLAYER
        mock_npc.return_value = SAMPLE_NPC_COMBAT
        ctx = _make_context()
        result = json.loads(await request_attack._func(
            ctx, target_id="goblin_1", weapon_or_spell="Longsword"
        ))
        if result["hit"]:
            mock_update.assert_called_once_with("goblin_1", result["target_hp_remaining"])
        else:
            mock_update.assert_not_called()

    @pytest.mark.asyncio
    @patch("tools.db.update_npc_hp", new_callable=AsyncMock)
    @patch("tools.db.get_npc_combat_stats", new_callable=AsyncMock)
    @patch("tools.db.get_player", new_callable=AsyncMock)
    async def test_publishes_event(self, mock_player, mock_npc, mock_update):
        mock_player.return_value = SAMPLE_PLAYER
        mock_npc.return_value = SAMPLE_NPC_COMBAT
        room = _make_mock_room()
        ctx = _make_context(room=room)
        await request_attack._func(
            ctx, target_id="goblin_1", weapon_or_spell="Longsword"
        )
        room.local_participant.publish_data.assert_called_once()
        call_data = json.loads(room.local_participant.publish_data.call_args[0][0])
        assert call_data["type"] == "dice_roll"
        assert call_data["roll_type"] == "attack"


# --- request_saving_throw ---

class TestRequestSavingThrow:
    @pytest.mark.asyncio
    @patch("tools.db.get_player", new_callable=AsyncMock)
    async def test_returns_result(self, mock_player):
        mock_player.return_value = SAMPLE_PLAYER
        ctx = _make_context()
        result = json.loads(await request_saving_throw._func(
            ctx, save_type="dexterity", dc=15, effect_on_fail="knocked prone"
        ))
        assert result["save_type"] == "dexterity"
        assert result["dc"] == 15
        assert result["outcome"] in ("success", "failure")

    @pytest.mark.asyncio
    @patch("tools.db.get_player", new_callable=AsyncMock)
    async def test_missing_player(self, mock_player):
        mock_player.return_value = None
        ctx = _make_context()
        result = json.loads(await request_saving_throw._func(
            ctx, save_type="dexterity", dc=15, effect_on_fail="prone"
        ))
        assert "error" in result

    @pytest.mark.asyncio
    @patch("tools.db.get_player", new_callable=AsyncMock)
    async def test_invalid_save_type(self, mock_player):
        mock_player.return_value = SAMPLE_PLAYER
        ctx = _make_context()
        result = json.loads(await request_saving_throw._func(
            ctx, save_type="luck", dc=15, effect_on_fail="cursed"
        ))
        assert "error" in result

    @pytest.mark.asyncio
    @patch("tools.db.get_player", new_callable=AsyncMock)
    async def test_publishes_event(self, mock_player):
        mock_player.return_value = SAMPLE_PLAYER
        room = _make_mock_room()
        ctx = _make_context(room=room)
        await request_saving_throw._func(
            ctx, save_type="wisdom", dc=12, effect_on_fail="frightened"
        )
        room.local_participant.publish_data.assert_called_once()
        call_data = json.loads(room.local_participant.publish_data.call_args[0][0])
        assert call_data["type"] == "dice_roll"
        assert call_data["roll_type"] == "saving_throw"


# --- roll_dice ---

class TestRollDice:
    @pytest.mark.asyncio
    async def test_valid_notation(self):
        ctx = _make_context()
        result = json.loads(await roll_dice._func(ctx, notation="2d6"))
        assert "rolls" in result
        assert "total" in result
        assert len(result["rolls"]) == 2

    @pytest.mark.asyncio
    async def test_invalid_notation(self):
        ctx = _make_context()
        result = json.loads(await roll_dice._func(ctx, notation="banana"))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_publishes_event(self):
        room = _make_mock_room()
        ctx = _make_context(room=room)
        await roll_dice._func(ctx, notation="d20")
        room.local_participant.publish_data.assert_called_once()
        call_data = json.loads(room.local_participant.publish_data.call_args[0][0])
        assert call_data["roll_type"] == "narrative"


# --- play_sound ---

class TestPlaySound:
    @pytest.mark.asyncio
    async def test_returns_confirmation(self):
        ctx = _make_context()
        result = json.loads(await play_sound._func(ctx, sound_name="thunder"))
        assert result["status"] == "playing"
        assert result["sound_name"] == "thunder"

    @pytest.mark.asyncio
    async def test_publishes_event(self):
        room = _make_mock_room()
        ctx = _make_context(room=room)
        await play_sound._func(ctx, sound_name="sword_clash")
        room.local_participant.publish_data.assert_called_once()
        call_data = json.loads(room.local_participant.publish_data.call_args[0][0])
        assert call_data["type"] == "play_sound"
        assert call_data["sound_name"] == "sword_clash"
