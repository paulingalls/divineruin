"""Tests for world query tools and helpers."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from session_data import SessionData
from tools import (
    _strip_hidden_dcs,
    _validate_id,
    apply_time_conditions,
    discover_hidden_element,
    enter_location,
    filter_knowledge,
    query_inventory,
    query_location,
    query_lore,
    query_npc,
)

# --- filter_knowledge tests ---


class TestFilterKnowledge:
    def test_free_always_included(self):
        knowledge = {"free": ["fact one", "fact two"]}
        assert filter_knowledge(knowledge, "hostile") == ["fact one", "fact two"]
        assert filter_knowledge(knowledge, "neutral") == ["fact one", "fact two"]
        assert filter_knowledge(knowledge, "trusted") == ["fact one", "fact two"]

    def test_friendly_gate_requires_friendly(self):
        knowledge = {
            "free": ["public"],
            "disposition >= friendly": ["secret-ish"],
        }
        assert filter_knowledge(knowledge, "hostile") == ["public"]
        assert filter_knowledge(knowledge, "wary") == ["public"]
        assert filter_knowledge(knowledge, "neutral") == ["public"]
        assert filter_knowledge(knowledge, "friendly") == ["public", "secret-ish"]
        assert filter_knowledge(knowledge, "trusted") == ["public", "secret-ish"]

    def test_trusted_gate_requires_trusted(self):
        knowledge = {
            "free": ["public"],
            "disposition >= friendly": ["mid"],
            "disposition >= trusted": ["deep secret"],
        }
        assert filter_knowledge(knowledge, "friendly") == ["public", "mid"]
        assert filter_knowledge(knowledge, "trusted") == ["public", "mid", "deep secret"]

    def test_quest_triggered_skipped(self):
        knowledge = {
            "free": ["public"],
            "quest_triggered": {
                "quest": "greyvale_anomaly",
                "stage": 4,
                "reveals": "something secret",
            },
        }
        result = filter_knowledge(knowledge, "trusted")
        assert result == ["public"]

    def test_empty_knowledge(self):
        assert filter_knowledge({}, "neutral") == []

    def test_unknown_disposition_defaults_neutral(self):
        knowledge = {
            "free": ["public"],
            "disposition >= friendly": ["secret"],
        }
        assert filter_knowledge(knowledge, "unknown_tier") == ["public"]

    def test_cautious_treated_as_neutral(self):
        knowledge = {
            "free": ["public"],
            "disposition >= friendly": ["secret"],
        }
        assert filter_knowledge(knowledge, "cautious") == ["public"]

    def test_all_tiers_hostile(self):
        knowledge = {
            "free": ["public"],
            "disposition >= friendly": ["mid"],
            "disposition >= trusted": ["deep"],
        }
        result = filter_knowledge(knowledge, "hostile")
        assert result == ["public"]


# --- apply_time_conditions tests ---


class TestApplyTimeConditions:
    def test_daytime_passthrough(self):
        location = {
            "description": "Sunny market",
            "atmosphere": "busy",
            "conditions": {
                "time_night": {
                    "description_override": "Dark market",
                    "atmosphere": "quiet",
                }
            },
        }
        result = apply_time_conditions(location, "day")
        assert result["description"] == "Sunny market"
        assert result["atmosphere"] == "busy"

    def test_nighttime_overrides(self):
        location = {
            "description": "Sunny market",
            "atmosphere": "busy",
            "conditions": {
                "time_night": {
                    "description_override": "Dark market",
                    "atmosphere": "quiet",
                }
            },
        }
        result = apply_time_conditions(location, "night")
        assert result["description"] == "Dark market"
        assert result["atmosphere"] == "quiet"

    def test_no_conditions(self):
        location = {"description": "A field", "atmosphere": "calm"}
        result = apply_time_conditions(location, "night")
        assert result["description"] == "A field"

    def test_does_not_mutate_original(self):
        location = {
            "description": "Original",
            "atmosphere": "original",
            "conditions": {
                "time_night": {
                    "description_override": "Changed",
                    "atmosphere": "changed",
                }
            },
        }
        apply_time_conditions(location, "night")
        assert location["description"] == "Original"


# --- _strip_hidden_dcs tests ---


class TestStripHiddenDCs:
    def test_strips_dc_and_discover_skill(self):
        location = {
            "hidden_elements": [
                {
                    "id": "secret_door",
                    "discover_skill": "perception",
                    "dc": 15,
                    "description": "A hidden passage",
                }
            ]
        }
        result = _strip_hidden_dcs(location)
        elem = result["hidden_elements"][0]
        assert elem == {"id": "secret_door", "description": "A hidden passage"}
        assert "dc" not in elem
        assert "discover_skill" not in elem

    def test_no_hidden_elements(self):
        location = {"description": "A room"}
        result = _strip_hidden_dcs(location)
        assert result == location


# --- Tool tests (mocked DB) ---


def _make_context(player_id="player_1", location_id="accord_guild_hall"):
    ctx = MagicMock()
    ctx.userdata = SessionData(player_id=player_id, location_id=location_id)
    return ctx


SAMPLE_LOCATION = {
    "id": "accord_guild_hall",
    "name": "Guild Hall",
    "description": "Heavy oak doors open onto a hall.",
    "atmosphere": "busy, purposeful",
    "key_features": ["the main counter"],
    "hidden_elements": [{"id": "notice", "discover_skill": "perception", "dc": 10, "description": "a notice"}],
    "exits": {"south": {"destination": "accord_market_square"}},
    "tags": ["guild"],
    "conditions": {},
}

SAMPLE_NPC = {
    "id": "guildmaster_torin",
    "name": "Guildmaster Torin",
    "role": "guild hall master",
    "personality": ["pragmatic"],
    "speech_style": "direct, wastes no words",
    "mannerisms": ["drums fingers on desk"],
    "appearance": "broad-shouldered",
    "default_disposition": "neutral",
    "knowledge": {
        "free": ["general guild operations"],
        "disposition >= friendly": ["he sent scouts north"],
        "disposition >= trusted": ["he suspects the temple"],
    },
    "secrets": ["his missing scout is personal"],
    "voice_notes": "deep baritone",
}


class TestQueryLocation:
    @pytest.mark.asyncio
    @patch("tools.db_queries.get_location", new_callable=AsyncMock)
    async def test_returns_location(self, mock_get):
        mock_get.return_value = SAMPLE_LOCATION
        ctx = _make_context()
        result = json.loads(await query_location._func(ctx, location_id="accord_guild_hall"))
        assert result["name"] == "Guild Hall"
        assert "dc" not in json.dumps(result["hidden_elements"])
        assert "discover_skill" not in json.dumps(result["hidden_elements"])

    @pytest.mark.asyncio
    @patch("tools.db_queries.get_location", new_callable=AsyncMock)
    async def test_missing_location(self, mock_get):
        mock_get.return_value = None
        ctx = _make_context()
        result = json.loads(await query_location._func(ctx, location_id="nonexistent"))
        assert "error" in result


class TestQueryNpc:
    @pytest.mark.asyncio
    @patch("tools.db_queries.get_npc_disposition", new_callable=AsyncMock)
    @patch("tools.db_queries.get_npc", new_callable=AsyncMock)
    async def test_returns_npc_neutral(self, mock_npc, mock_disp):
        mock_npc.return_value = SAMPLE_NPC
        mock_disp.return_value = None  # falls back to default_disposition
        ctx = _make_context()
        result = json.loads(await query_npc._func(ctx, npc_id="guildmaster_torin"))
        assert result["name"] == "Guildmaster Torin"
        assert result["disposition"] == "neutral"
        assert "general guild operations" in result["knowledge"]
        assert "he sent scouts north" not in result["knowledge"]
        assert "secrets" not in result

    @pytest.mark.asyncio
    @patch("tools.db_queries.get_npc_disposition", new_callable=AsyncMock)
    @patch("tools.db_queries.get_npc", new_callable=AsyncMock)
    async def test_friendly_reveals_more(self, mock_npc, mock_disp):
        mock_npc.return_value = SAMPLE_NPC
        mock_disp.return_value = "friendly"
        ctx = _make_context()
        result = json.loads(await query_npc._func(ctx, npc_id="guildmaster_torin"))
        assert result["disposition"] == "friendly"
        assert "he sent scouts north" in result["knowledge"]
        assert "he suspects the temple" not in result["knowledge"]

    @pytest.mark.asyncio
    @patch("tools.db_queries.get_npc_disposition", new_callable=AsyncMock)
    @patch("tools.db_queries.get_npc", new_callable=AsyncMock)
    async def test_trusted_reveals_all(self, mock_npc, mock_disp):
        mock_npc.return_value = SAMPLE_NPC
        mock_disp.return_value = "trusted"
        ctx = _make_context()
        result = json.loads(await query_npc._func(ctx, npc_id="guildmaster_torin"))
        assert "he suspects the temple" in result["knowledge"]

    @pytest.mark.asyncio
    @patch("tools.db_queries.get_npc", new_callable=AsyncMock)
    async def test_missing_npc(self, mock_npc):
        mock_npc.return_value = None
        ctx = _make_context()
        result = json.loads(await query_npc._func(ctx, npc_id="nobody"))
        assert "error" in result


class TestQueryLore:
    @pytest.mark.asyncio
    @patch("tools.db_queries.search_lore", new_callable=AsyncMock)
    async def test_returns_entries(self, mock_search):
        mock_search.return_value = [
            {"title": "The Hollow", "category": "cosmology", "content": "Bad stuff.", "tags": ["hollow"]}
        ]
        ctx = _make_context()
        result = json.loads(await query_lore._func(ctx, topic="hollow"))
        assert len(result["entries"]) == 1
        assert result["entries"][0]["title"] == "The Hollow"

    @pytest.mark.asyncio
    @patch("tools.db_queries.search_lore", new_callable=AsyncMock)
    async def test_no_matches(self, mock_search):
        mock_search.return_value = []
        ctx = _make_context()
        result = json.loads(await query_lore._func(ctx, topic="nonexistent"))
        assert "note" in result


class TestQueryInventory:
    @pytest.mark.asyncio
    @patch("tools.db_queries.get_player_inventory", new_callable=AsyncMock)
    async def test_returns_items(self, mock_inv):
        mock_inv.return_value = [
            {
                "name": "Sealed Research Tablet",
                "type": "quest_item",
                "description": "A warm stone tablet.",
                "rarity": "rare",
                "effects": [],
                "lore": "Research notes from an Aelindran outpost.",
            }
        ]
        ctx = _make_context()
        result = json.loads(await query_inventory._func(ctx))
        assert len(result["items"]) == 1
        assert result["items"][0]["name"] == "Sealed Research Tablet"
        mock_inv.assert_awaited_once_with("player_1")

    @pytest.mark.asyncio
    @patch("tools.db_queries.get_player_inventory", new_callable=AsyncMock)
    async def test_empty_inventory(self, mock_inv):
        mock_inv.return_value = []
        ctx = _make_context()
        result = json.loads(await query_inventory._func(ctx))
        assert "note" in result


# --- enter_location tests ---

SAMPLE_NPC_RAW = {
    "id": "guildmaster_torin",
    "name": "Guildmaster Torin",
    "role": "guild hall master",
    "default_disposition": "neutral",
    "voice_notes": "deep baritone",
    "schedule": {"07:00-22:00": "accord_guild_hall"},
}

SAMPLE_TARGET = {
    "npc_id": "guild_training_dummy",
    "name": "Training Dummy",
    "location": "accord_guild_hall",
    "ac": 10,
    "hp": {"current": 50, "max": 50},
    "description": "A battered wooden post.",
}

SAMPLE_PLAYER = {
    "player_id": "player_1",
    "name": "Kael",
    "class": "warrior",
    "level": 1,
    "hp": {"current": 25, "max": 25},
    "ac": 14,
    "equipment": {
        "main_hand": {
            "name": "Longsword",
            "damage": "1d8",
            "damage_type": "slashing",
            "properties": [],
        }
    },
}


class TestEnterLocation:
    @pytest.mark.asyncio
    @patch("tools.db_queries.get_player", new_callable=AsyncMock)
    @patch("tools.db_queries.get_targets_at_location", new_callable=AsyncMock)
    @patch("tools.db_queries.get_npc_dispositions", new_callable=AsyncMock)
    @patch("tools.db_queries.get_npcs_at_location", new_callable=AsyncMock)
    @patch("tools.db_queries.get_location", new_callable=AsyncMock)
    async def test_returns_full_context(self, mock_loc, mock_npcs, mock_disp, mock_targets, mock_player):
        mock_loc.return_value = SAMPLE_LOCATION
        mock_npcs.return_value = [SAMPLE_NPC_RAW]
        mock_disp.return_value = {}
        mock_targets.return_value = [SAMPLE_TARGET]
        mock_player.return_value = SAMPLE_PLAYER
        ctx = _make_context()
        result = json.loads(await enter_location._func(ctx, location_id="accord_guild_hall"))

        assert result["location"]["name"] == "Guild Hall"
        assert len(result["npcs"]) == 1
        assert result["npcs"][0]["id"] == "guildmaster_torin"
        assert result["npcs"][0]["disposition"] == "neutral"
        assert len(result["targets"]) == 1
        assert result["targets"][0]["id"] == "guild_training_dummy"
        assert result["targets"][0]["ac"] == 10
        assert result["player"]["name"] == "Kael"
        assert result["player"]["weapon"] == "Longsword"

    @pytest.mark.asyncio
    @patch("tools.db_queries.get_location", new_callable=AsyncMock)
    async def test_missing_location(self, mock_loc):
        mock_loc.return_value = None
        ctx = _make_context()
        result = json.loads(await enter_location._func(ctx, location_id="nowhere"))
        assert "error" in result

    @pytest.mark.asyncio
    @patch("tools.db_queries.get_player", new_callable=AsyncMock)
    @patch("tools.db_queries.get_targets_at_location", new_callable=AsyncMock)
    @patch("tools.db_queries.get_npcs_at_location", new_callable=AsyncMock)
    @patch("tools.db_queries.get_location", new_callable=AsyncMock)
    async def test_empty_npcs_and_targets(self, mock_loc, mock_npcs, mock_targets, mock_player):
        mock_loc.return_value = SAMPLE_LOCATION
        mock_npcs.return_value = []
        mock_targets.return_value = []
        mock_player.return_value = SAMPLE_PLAYER
        ctx = _make_context()
        result = json.loads(await enter_location._func(ctx, location_id="accord_guild_hall"))

        assert result["npcs"] == []
        assert result["targets"] == []
        assert result["location"]["name"] == "Guild Hall"


# --- Night time condition tests for tools ---


NIGHT_LOCATION = {
    "id": "accord_market_square",
    "name": "Market Square",
    "description": "Sunny market",
    "atmosphere": "busy",
    "key_features": ["a fountain"],
    "hidden_elements": [],
    "exits": {"north": {"destination": "accord_guild_hall"}},
    "tags": ["market"],
    "conditions": {
        "time_night": {
            "description_override": "Dark empty market",
            "atmosphere": "quiet, reflective",
        }
    },
}


class TestNightConditionsInTools:
    @pytest.mark.asyncio
    @patch("tools.db_queries.get_player", new_callable=AsyncMock)
    @patch("tools.db_queries.get_targets_at_location", new_callable=AsyncMock)
    @patch("tools.db_queries.get_npc_dispositions", new_callable=AsyncMock)
    @patch("tools.db_queries.get_npcs_at_location", new_callable=AsyncMock)
    @patch("tools.db_queries.get_location", new_callable=AsyncMock)
    async def test_build_scene_applies_night(self, mock_loc, mock_npcs, mock_disp, mock_targets, mock_player):
        mock_loc.return_value = NIGHT_LOCATION
        mock_npcs.return_value = []
        mock_targets.return_value = []
        mock_player.return_value = SAMPLE_PLAYER
        ctx = _make_context()
        ctx.userdata.world_time = "night"
        result = json.loads(await enter_location._func(ctx, location_id="accord_market_square"))
        assert result["location"]["description"] == "Dark empty market"
        assert result["location"]["atmosphere"] == "quiet, reflective"

    @pytest.mark.asyncio
    @patch("tools.db_queries.get_player", new_callable=AsyncMock)
    @patch("tools.db_queries.get_targets_at_location", new_callable=AsyncMock)
    @patch("tools.db_queries.get_npc_dispositions", new_callable=AsyncMock)
    @patch("tools.db_queries.get_npcs_at_location", new_callable=AsyncMock)
    @patch("tools.db_queries.get_location", new_callable=AsyncMock)
    async def test_build_scene_day_no_override(self, mock_loc, mock_npcs, mock_disp, mock_targets, mock_player):
        mock_loc.return_value = NIGHT_LOCATION
        mock_npcs.return_value = []
        mock_targets.return_value = []
        mock_player.return_value = SAMPLE_PLAYER
        ctx = _make_context()
        ctx.userdata.world_time = "day"
        result = json.loads(await enter_location._func(ctx, location_id="accord_market_square"))
        assert result["location"]["description"] == "Sunny market"

    @pytest.mark.asyncio
    @patch("tools.db_queries.get_location", new_callable=AsyncMock)
    async def test_query_location_applies_night(self, mock_loc):
        mock_loc.return_value = NIGHT_LOCATION
        ctx = _make_context()
        ctx.userdata.world_time = "night"
        result = json.loads(await query_location._func(ctx, location_id="accord_market_square"))
        assert result["description"] == "Dark empty market"

    @pytest.mark.asyncio
    @patch("tools.db_queries.get_location", new_callable=AsyncMock)
    async def test_query_location_day_no_override(self, mock_loc):
        mock_loc.return_value = NIGHT_LOCATION
        ctx = _make_context()
        ctx.userdata.world_time = "day"
        result = json.loads(await query_location._func(ctx, location_id="accord_market_square"))
        assert result["description"] == "Sunny market"


# --- discover_hidden_element tests ---


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


class TestDiscoverHiddenElement:
    @pytest.mark.asyncio
    @patch("tools.db_mutations.set_player_flag", new_callable=AsyncMock)
    @patch("check_tools.publish_game_event", new_callable=AsyncMock)
    @patch("tools.db_queries.get_player", new_callable=AsyncMock)
    @patch("tools.db_queries.get_location", new_callable=AsyncMock)
    async def test_successful_discovery(self, mock_loc, mock_player, mock_event, mock_set_flag):
        mock_loc.return_value = LOCATION_WITH_HIDDEN
        mock_player.return_value = DISCOVER_PLAYER
        ctx = _make_context(location_id="test_location")

        with patch("check_resolution.dice_roll") as mock_dice:
            from dice import DiceResult

            mock_dice.return_value = DiceResult(notation="d20", rolls=[15], dropped=[], total=15)
            result = json.loads(await discover_hidden_element._func(ctx, element_id="secret_door"))

        assert result["outcome"] == "discovered"
        assert "hidden passage" in result["description"]
        assert result["element_id"] == "secret_door"
        mock_set_flag.assert_called_once_with("player_1", "secret_door.discovered", True)

    @pytest.mark.asyncio
    @patch("check_tools.publish_game_event", new_callable=AsyncMock)
    @patch("tools.db_queries.get_player", new_callable=AsyncMock)
    @patch("tools.db_queries.get_location", new_callable=AsyncMock)
    async def test_failed_discovery(self, mock_loc, mock_player, mock_event):
        mock_loc.return_value = LOCATION_WITH_HIDDEN
        mock_player.return_value = DISCOVER_PLAYER
        ctx = _make_context(location_id="test_location")

        with patch("check_resolution.dice_roll") as mock_dice:
            from dice import DiceResult

            mock_dice.return_value = DiceResult(notation="d20", rolls=[3], dropped=[], total=3)
            result = json.loads(await discover_hidden_element._func(ctx, element_id="secret_door"))

        assert result["outcome"] == "not_found"
        assert "description" not in result

    @pytest.mark.asyncio
    @patch("tools.db_queries.get_location", new_callable=AsyncMock)
    async def test_invalid_element_id(self, mock_loc):
        mock_loc.return_value = LOCATION_WITH_HIDDEN
        ctx = _make_context(location_id="test_location")
        result = json.loads(await discover_hidden_element._func(ctx, element_id="nonexistent"))
        assert "error" in result

    @pytest.mark.asyncio
    @patch("tools.db_queries.get_location", new_callable=AsyncMock)
    async def test_location_not_found(self, mock_loc):
        mock_loc.return_value = None
        ctx = _make_context(location_id="nowhere")
        result = json.loads(await discover_hidden_element._func(ctx, element_id="secret_door"))
        assert "error" in result

    @pytest.mark.asyncio
    @patch("check_tools.publish_game_event", new_callable=AsyncMock)
    @patch("tools.db_queries.get_player", new_callable=AsyncMock)
    @patch("tools.db_queries.get_location", new_callable=AsyncMock)
    async def test_blocks_repeated_attempt(self, mock_loc, mock_player, mock_event):
        mock_loc.return_value = LOCATION_WITH_HIDDEN
        mock_player.return_value = DISCOVER_PLAYER
        ctx = _make_context(location_id="test_location")

        with patch("check_resolution.dice_roll") as mock_dice:
            from dice import DiceResult

            mock_dice.return_value = DiceResult(notation="d20", rolls=[3], dropped=[], total=3)
            await discover_hidden_element._func(ctx, element_id="secret_door")

        result = json.loads(await discover_hidden_element._func(ctx, element_id="secret_door"))
        assert "error" in result
        assert "Already searched" in result["error"]

    @pytest.mark.asyncio
    @patch("tools.db_mutations.set_player_flag", new_callable=AsyncMock)
    @patch("check_tools.publish_game_event", new_callable=AsyncMock)
    @patch("tools.db_queries.get_player", new_callable=AsyncMock)
    @patch("tools.db_queries.get_location", new_callable=AsyncMock)
    async def test_dice_roll_event_has_no_dc(self, mock_loc, mock_player, mock_event, mock_set_flag):
        """DC should not be included in the client-facing dice_roll event."""
        mock_loc.return_value = LOCATION_WITH_HIDDEN
        mock_player.return_value = DISCOVER_PLAYER
        ctx = _make_context(location_id="test_location")

        with patch("check_resolution.dice_roll") as mock_dice:
            from dice import DiceResult

            mock_dice.return_value = DiceResult(notation="d20", rolls=[15], dropped=[], total=15)
            await discover_hidden_element._func(ctx, element_id="secret_door")

        event_payload = mock_event.call_args[0][2]
        assert "dc" not in event_payload


# --- _validate_id tests ---


class TestValidateId:
    def test_valid_id(self):
        assert _validate_id("accord_guild_hall", "location_id") is None

    def test_valid_id_with_hyphens(self):
        assert _validate_id("npc-123", "npc_id") is None

    def test_empty_id(self):
        result = json.loads(_validate_id("", "location_id"))
        assert "error" in result

    def test_too_long_id(self):
        result = json.loads(_validate_id("a" * 129, "location_id"))
        assert "error" in result

    def test_special_characters_rejected(self):
        result = json.loads(_validate_id("id; DROP TABLE", "location_id"))
        assert "error" in result

    def test_path_traversal_rejected(self):
        result = json.loads(_validate_id("../etc/passwd", "location_id"))
        assert "error" in result
