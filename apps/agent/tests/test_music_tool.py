"""Tests for combat difficulty in start_combat."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import event_types as E
from combat_init import _start_combat_impl
from session_data import SessionData


def _make_context(player_id="player_1", location_id="accord_guild_hall"):
    ctx = MagicMock()
    ctx.userdata = SessionData(player_id=player_id, location_id=location_id)
    return ctx


class TestStartCombatDifficulty:
    """Verify start_combat event payload includes difficulty field."""

    @pytest.mark.asyncio
    @patch("combat_init.publish_game_event", new_callable=AsyncMock)
    @patch("combat_init._publish_sounds", new_callable=AsyncMock)
    async def test_combat_started_includes_difficulty(self, mock_sounds, mock_event):
        mock_content = MagicMock()
        mock_content.get_encounter_template = AsyncMock(
            return_value={
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
        )
        mock_content.get_npc = AsyncMock(return_value=None)
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(
            return_value={
                "name": "Kael",
                "hp": {"current": 25, "max": 30},
                "ac": 15,
                "attributes": {"dexterity": 12},
                "level": 3,
            }
        )
        mock_mutations = MagicMock()
        mock_mutations.save_combat_state = AsyncMock()

        ctx = _make_context()
        ctx.userdata.combat_state = None
        ctx.userdata.companion = None

        raw = await _start_combat_impl(
            ctx,
            encounter_id="goblin_ambush",
            encounter_description="Goblins jump from the bushes",
            mutations=mock_mutations,
            queries=mock_queries,
            content=mock_content,
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
    @patch("combat_init.publish_game_event", new_callable=AsyncMock)
    @patch("combat_init._publish_sounds", new_callable=AsyncMock)
    async def test_combat_started_defaults_to_moderate(self, mock_sounds, mock_event):
        mock_content = MagicMock()
        mock_content.get_encounter_template = AsyncMock(
            return_value={
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
        )
        mock_content.get_npc = AsyncMock(return_value=None)
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(
            return_value={
                "name": "Kael",
                "hp": {"current": 25, "max": 30},
                "ac": 15,
                "attributes": {"dexterity": 12},
                "level": 3,
            }
        )
        mock_mutations = MagicMock()
        mock_mutations.save_combat_state = AsyncMock()

        ctx = _make_context()
        ctx.userdata.combat_state = None
        ctx.userdata.companion = None

        await _start_combat_impl(
            ctx,
            encounter_id="bar_fight",
            encounter_description="A bar fight breaks out",
            mutations=mock_mutations,
            queries=mock_queries,
            content=mock_content,
        )

        combat_started_calls = [c for c in mock_event.call_args_list if c[0][1] == E.COMBAT_STARTED]
        assert len(combat_started_calls) == 1
        payload = combat_started_calls[0][0][2]
        assert payload["difficulty"] == "moderate"
