import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sample_fixtures import load_test_creature

import event_types as E
from combat_init import _start_combat_impl
from session_data import SessionData


def _make_context(player_id="player_1", location_id="accord_guild_hall"):
    ctx = MagicMock()
    ctx.userdata = SessionData(player_id=player_id, location_id=location_id)
    return ctx


class TestStartCombatDifficulty:
    @pytest.mark.asyncio
    @patch("combat_init.publish_game_event", new_callable=AsyncMock)
    @patch("combat_init._publish_sounds", new_callable=AsyncMock)
    async def test_combat_started_includes_difficulty(self, mock_sounds, mock_event):
        mock_content = MagicMock()
        mock_content.load_creature_enemy = load_test_creature
        mock_content.get_encounter_template = AsyncMock(
            return_value={
                "scene_placement": {
                    "party_start": {"x": 0, "y": 0, "z": 0},
                    "companion_start": {"x": 0, "y": 5, "z": 0},
                    "actors": {"goblin_1": {"x": 20, "y": 0, "z": 0}},
                    "locations": {},
                    "zones": {},
                },
                "recommended_party_level": 1,
                "name": "Goblin Ambush",
                "difficulty": "hard",
                "enemies": [{"id": "goblin_1", "creature_id": "fixture_goblin", "role": "standard"}],
            }
        )
        mock_content.get_npc = AsyncMock(return_value=None)
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(
            return_value={
                "speed": 30,
                "name": "Kael",
                "class": "warrior",
                "hp": {"current": 25, "max": 30},
                "ac": 15,
                "attributes": {"dexterity": 12},
                "level": 3,
            }
        )
        mock_queries.get_player_inventory = AsyncMock(return_value=[])
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

        combat_started_calls = [c for c in mock_event.call_args_list if c[0][1] == E.COMBAT_STARTED]
        assert len(combat_started_calls) == 1
        payload = combat_started_calls[0][0][2]
        assert payload["difficulty"] == "hard"

    @pytest.mark.asyncio
    @patch("combat_init.publish_game_event", new_callable=AsyncMock)
    @patch("combat_init._publish_sounds", new_callable=AsyncMock)
    async def test_combat_started_defaults_to_moderate(self, mock_sounds, mock_event):
        mock_content = MagicMock()
        mock_content.load_creature_enemy = load_test_creature
        mock_content.get_encounter_template = AsyncMock(
            return_value={
                "scene_placement": {
                    "party_start": {"x": 0, "y": 0, "z": 0},
                    "companion_start": {"x": 0, "y": 5, "z": 0},
                    "actors": {"thug_1": {"x": 20, "y": 0, "z": 0}},
                    "locations": {},
                    "zones": {},
                },
                "recommended_party_level": 1,
                "name": "Bar Fight",
                "enemies": [{"id": "thug_1", "creature_id": "fixture_goblin", "role": "standard"}],
            }
        )
        mock_content.get_npc = AsyncMock(return_value=None)
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(
            return_value={
                "speed": 30,
                "name": "Kael",
                "class": "warrior",
                "hp": {"current": 25, "max": 30},
                "ac": 15,
                "attributes": {"dexterity": 12},
                "level": 3,
            }
        )
        mock_queries.get_player_inventory = AsyncMock(return_value=[])
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
