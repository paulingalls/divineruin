"""Tests for set_music_state tool and combat difficulty in start_combat."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import event_types as E
from session_data import SessionData
from tools import set_music_state


def _make_context(player_id="player_1", location_id="accord_guild_hall"):
    ctx = MagicMock()
    ctx.userdata = SessionData(player_id=player_id, location_id=location_id)
    return ctx


class TestSetMusicState:
    @pytest.mark.asyncio
    @patch("tools.publish_game_event", new_callable=AsyncMock)
    async def test_wonder_publishes_event(self, mock_event):
        ctx = _make_context()
        result = json.loads(await set_music_state._func(ctx, music_state="wonder"))
        assert result["status"] == "set"
        assert result["music_state"] == "wonder"
        mock_event.assert_called_once()
        call_args = mock_event.call_args[0]
        assert call_args[1] == E.SET_MUSIC_STATE
        assert call_args[2]["music_state"] == "wonder"

    @pytest.mark.asyncio
    @patch("tools.publish_game_event", new_callable=AsyncMock)
    async def test_sorrow_publishes_event(self, mock_event):
        ctx = _make_context()
        result = json.loads(await set_music_state._func(ctx, music_state="sorrow"))
        assert result["status"] == "set"
        assert result["music_state"] == "sorrow"

    @pytest.mark.asyncio
    @patch("tools.publish_game_event", new_callable=AsyncMock)
    async def test_tension_publishes_event(self, mock_event):
        ctx = _make_context()
        result = json.loads(await set_music_state._func(ctx, music_state="tension"))
        assert result["status"] == "set"

    @pytest.mark.asyncio
    @patch("tools.publish_game_event", new_callable=AsyncMock)
    async def test_silence_publishes_event(self, mock_event):
        ctx = _make_context()
        result = json.loads(await set_music_state._func(ctx, music_state="silence"))
        assert result["status"] == "set"

    @pytest.mark.asyncio
    async def test_combat_standard_returns_error(self):
        ctx = _make_context()
        result = json.loads(await set_music_state._func(ctx, music_state="combat_standard"))
        assert "error" in result
        assert "combat_standard" in result["error"]

    @pytest.mark.asyncio
    async def test_exploration_returns_error(self):
        ctx = _make_context()
        result = json.loads(await set_music_state._func(ctx, music_state="exploration"))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_invalid_state_returns_error(self):
        ctx = _make_context()
        result = json.loads(await set_music_state._func(ctx, music_state="party_time"))
        assert "error" in result
        assert "party_time" in result["error"]


class TestStartCombatDifficulty:
    """Verify start_combat event payload includes difficulty field."""

    @pytest.mark.asyncio
    @patch("tools.publish_game_event", new_callable=AsyncMock)
    @patch("tools._publish_sounds", new_callable=AsyncMock)
    @patch("tools.db_mutations.save_combat_state", new_callable=AsyncMock)
    @patch("tools.db_queries.get_player", new_callable=AsyncMock)
    @patch("tools.db_queries.get_encounter_template", new_callable=AsyncMock)
    async def test_combat_started_includes_difficulty(
        self, mock_encounter, mock_player, mock_save, mock_sounds, mock_event
    ):
        mock_encounter.return_value = {
            "name": "Goblin Ambush",
            "difficulty": "hard",
            "enemies": [
                {
                    "id": "goblin_1",
                    "name": "Goblin Scout",
                    "hp": 7,
                    "ac": 12,
                    "attributes": {"dexterity": 14},
                    "level": 1,
                    "xp_value": 25,
                }
            ],
        }
        mock_player.return_value = {
            "name": "Kael",
            "hp": {"current": 25, "max": 30},
            "ac": 15,
            "attributes": {"dexterity": 12},
            "level": 3,
        }
        ctx = _make_context()
        ctx.userdata.combat_state = None
        ctx.userdata.companion = None

        from tools import start_combat

        raw = await start_combat._func(
            ctx, encounter_id="goblin_ambush", encounter_description="Goblins jump from the bushes"
        )
        _, json_str = raw
        result = json.loads(json_str)
        assert result["combat_id"]

        # Find the combat_started event call
        combat_started_calls = [c for c in mock_event.call_args_list if c[0][1] == E.COMBAT_STARTED]
        assert len(combat_started_calls) == 1
        payload = combat_started_calls[0][0][2]
        assert payload["difficulty"] == "hard"

    @pytest.mark.asyncio
    @patch("tools.publish_game_event", new_callable=AsyncMock)
    @patch("tools._publish_sounds", new_callable=AsyncMock)
    @patch("tools.db_mutations.save_combat_state", new_callable=AsyncMock)
    @patch("tools.db_queries.get_player", new_callable=AsyncMock)
    @patch("tools.db_queries.get_encounter_template", new_callable=AsyncMock)
    async def test_combat_started_defaults_to_moderate(
        self, mock_encounter, mock_player, mock_save, mock_sounds, mock_event
    ):
        mock_encounter.return_value = {
            "name": "Bar Fight",
            "enemies": [
                {
                    "id": "thug_1",
                    "name": "Thug",
                    "hp": 10,
                    "ac": 11,
                    "attributes": {"strength": 14},
                    "level": 1,
                    "xp_value": 25,
                }
            ],
        }
        mock_player.return_value = {
            "name": "Kael",
            "hp": {"current": 25, "max": 30},
            "ac": 15,
            "attributes": {"dexterity": 12},
            "level": 3,
        }
        ctx = _make_context()
        ctx.userdata.combat_state = None
        ctx.userdata.companion = None

        from tools import start_combat

        await start_combat._func(ctx, encounter_id="bar_fight", encounter_description="A bar fight breaks out")

        combat_started_calls = [c for c in mock_event.call_args_list if c[0][1] == E.COMBAT_STARTED]
        assert len(combat_started_calls) == 1
        payload = combat_started_calls[0][0][2]
        assert payload["difficulty"] == "moderate"
