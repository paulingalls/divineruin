"""Integration tests for mechanics tools (mocked DB + room)."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError

import event_types as E
from check_tools import (
    _mark_skill_breakthrough_impl,
    _request_attack_impl,
)
from environment_tools import play_sound
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


# --- request_attack ---


class TestRequestAttack:
    @pytest.mark.asyncio
    async def test_returns_result(self):
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
        mock_queries.get_npc_combat_stats = AsyncMock(return_value=SAMPLE_NPC_COMBAT)
        mock_mutations = MagicMock()
        mock_mutations.update_npc_hp = AsyncMock()
        ctx = _make_context()
        result = json.loads(
            await _request_attack_impl(
                ctx,
                target_id="goblin_1",
                weapon_name="Longsword",
                queries=mock_queries,
                mutations=mock_mutations,
            )
        )
        assert "hit" in result
        assert "damage" in result
        assert "narrative_hint" in result

    @pytest.mark.asyncio
    async def test_missing_player(self):
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(return_value=None)
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _request_attack_impl(
                ctx,
                target_id="goblin_1",
                weapon_name="Longsword",
                queries=mock_queries,
            )

    @pytest.mark.asyncio
    async def test_missing_weapon(self):
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
        ctx = _make_context()
        with pytest.raises(ToolError, match="Warhammer"):
            await _request_attack_impl(
                ctx,
                target_id="goblin_1",
                weapon_name="Warhammer",
                queries=mock_queries,
            )

    @pytest.mark.asyncio
    async def test_spell_name_is_not_routed_as_weapon(self):
        # AC5: after the weapon-only split, a spell name does NOT cast — it fails the
        # equipment lookup like any non-weapon. Spells route through cast_spell instead.
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
        ctx = _make_context()
        with pytest.raises(ToolError, match="not found in equipment"):
            await _request_attack_impl(
                ctx,
                target_id="goblin_1",
                weapon_name="Arcane Bolt",
                queries=mock_queries,
            )

    @pytest.mark.asyncio
    async def test_missing_target(self):
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
        mock_queries.get_npc_combat_stats = AsyncMock(return_value=None)
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _request_attack_impl(
                ctx,
                target_id="ghost",
                weapon_name="Longsword",
                queries=mock_queries,
            )

    @pytest.mark.asyncio
    async def test_hp_updated_on_hit(self):
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
        mock_queries.get_npc_combat_stats = AsyncMock(return_value=SAMPLE_NPC_COMBAT)
        mock_mutations = MagicMock()
        mock_mutations.update_npc_hp = AsyncMock()
        ctx = _make_context()
        result = json.loads(
            await _request_attack_impl(
                ctx,
                target_id="goblin_1",
                weapon_name="Longsword",
                queries=mock_queries,
                mutations=mock_mutations,
            )
        )
        if result["hit"]:
            mock_mutations.update_npc_hp.assert_called_once_with("goblin_1", result["target_hp_remaining"])
        else:
            mock_mutations.update_npc_hp.assert_not_called()

    @pytest.mark.asyncio
    async def test_publishes_event(self):
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
        mock_queries.get_npc_combat_stats = AsyncMock(return_value=SAMPLE_NPC_COMBAT)
        mock_mutations = MagicMock()
        mock_mutations.update_npc_hp = AsyncMock()
        room = _make_mock_room()
        ctx = _make_context(room=room)
        await _request_attack_impl(
            ctx,
            target_id="goblin_1",
            weapon_name="Longsword",
            queries=mock_queries,
            mutations=mock_mutations,
        )
        room.local_participant.publish_data.assert_called_once()
        call_data = json.loads(room.local_participant.publish_data.call_args[0][0])
        assert call_data["type"] == E.DICE_ROLL
        assert call_data["roll_type"] == "attack"


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
