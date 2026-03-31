"""Tests for prompt building (warm layer)."""

from unittest.mock import AsyncMock, patch

from prompts import build_full_prompt, build_system_prompt, build_warm_layer

SAMPLE_LOCATION = {
    "id": "accord_guild_hall",
    "name": "Guild Hall",
    "description": "Heavy oak doors open onto a hall.",
    "atmosphere": "busy, purposeful",
    "key_features": ["the main counter"],
    "hidden_elements": [],
    "exits": {"south": {"destination": "accord_market_square"}},
    "tags": ["guild"],
    "conditions": {
        "time_night": {
            "description_override": "The guild hall is dim and quiet.",
            "atmosphere": "hushed",
        }
    },
}

SAMPLE_NPC_RAW = {
    "id": "guildmaster_torin",
    "name": "Guildmaster Torin",
    "role": "guild hall master",
    "default_disposition": "neutral",
    "voice_notes": "deep baritone",
    "schedule": {"07:00-22:00": "accord_guild_hall"},
}

SAMPLE_QUEST = {
    "quest_id": "greyvale_anomaly",
    "quest_name": "The Greyvale Anomaly",
    "current_stage": 1,
    "stages": [
        {"id": 0, "objective": "Investigate the strange lights."},
        {"id": 1, "objective": "Find the source of the anomaly."},
    ],
}


class TestBuildWarmLayer:
    @patch("db.get_active_player_quests", new_callable=AsyncMock)
    @patch("db.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db.get_location", new_callable=AsyncMock)
    async def test_includes_location(self, mock_loc, mock_npcs, mock_disp, mock_quests):
        mock_loc.return_value = SAMPLE_LOCATION
        mock_npcs.return_value = []
        mock_quests.return_value = []
        result = await build_warm_layer("accord_guild_hall", "player_1", "evening")
        assert "Guild Hall" in result
        assert "evening" in result

    @patch("db.get_active_player_quests", new_callable=AsyncMock)
    @patch("db.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db.get_location", new_callable=AsyncMock)
    async def test_includes_npcs(self, mock_loc, mock_npcs, mock_disp, mock_quests):
        mock_loc.return_value = SAMPLE_LOCATION
        mock_npcs.return_value = [SAMPLE_NPC_RAW]
        mock_disp.return_value = {}
        mock_quests.return_value = []
        result = await build_warm_layer("accord_guild_hall", "player_1", "evening")
        assert "Guildmaster Torin" in result
        assert "neutral" in result

    @patch("db.get_active_player_quests", new_callable=AsyncMock)
    @patch("db.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db.get_location", new_callable=AsyncMock)
    async def test_includes_quests(self, mock_loc, mock_npcs, mock_disp, mock_quests):
        mock_loc.return_value = SAMPLE_LOCATION
        mock_npcs.return_value = []
        mock_quests.return_value = [SAMPLE_QUEST]
        result = await build_warm_layer("accord_guild_hall", "player_1", "evening")
        assert "Greyvale Anomaly" in result
        assert "Find the source" in result

    @patch("db.get_active_player_quests", new_callable=AsyncMock)
    @patch("db.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db.get_location", new_callable=AsyncMock)
    async def test_night_applies_time_conditions(self, mock_loc, mock_npcs, mock_disp, mock_quests):
        mock_loc.return_value = SAMPLE_LOCATION
        mock_npcs.return_value = []
        mock_quests.return_value = []
        result = await build_warm_layer("accord_guild_hall", "player_1", "night")
        assert "dim and quiet" in result
        assert "hushed" in result


class TestBuildWarmLayerExits:
    @patch("db.get_active_player_quests", new_callable=AsyncMock)
    @patch("db.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db.get_location", new_callable=AsyncMock)
    async def test_exits_appear_in_warm_layer(self, mock_loc, mock_npcs, mock_disp, mock_quests):
        mock_loc.return_value = SAMPLE_LOCATION
        mock_npcs.return_value = []
        mock_quests.return_value = []
        result = await build_warm_layer("accord_guild_hall", "player_1", "evening")
        assert "EXITS" in result
        assert "south" in result
        assert "accord_market_square" in result

    @patch("db.get_active_player_quests", new_callable=AsyncMock)
    @patch("db.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db.get_location", new_callable=AsyncMock)
    async def test_blocked_exit_shows_requires(self, mock_loc, mock_npcs, mock_disp, mock_quests):
        location_with_blocked = {
            **SAMPLE_LOCATION,
            "exits": {
                "south": {"destination": "accord_market_square"},
                "east": {"destination": "accord_temple_row", "requires": "temple_key"},
            },
        }
        mock_loc.return_value = location_with_blocked
        mock_npcs.return_value = []
        mock_quests.return_value = []
        result = await build_warm_layer("accord_guild_hall", "player_1", "evening")
        assert "blocked" in result
        assert "temple_key" in result

    @patch("db.get_active_player_quests", new_callable=AsyncMock)
    @patch("db.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db.get_location", new_callable=AsyncMock)
    async def test_no_exits_no_section(self, mock_loc, mock_npcs, mock_disp, mock_quests):
        location_no_exits = {**SAMPLE_LOCATION, "exits": {}}
        mock_loc.return_value = location_no_exits
        mock_npcs.return_value = []
        mock_quests.return_value = []
        result = await build_warm_layer("accord_guild_hall", "player_1", "evening")
        assert "EXITS" not in result


class TestNavigationPromptIncluded:
    def test_system_prompt_includes_navigation(self):
        prompt = build_system_prompt("accord_guild_hall")
        assert "discover_hidden_element" in prompt
        assert "Navigation" in prompt


class TestRegionTypePrompts:
    """System prompts vary by region_type."""

    def test_city_prompt_is_default(self):
        default = build_system_prompt("loc")
        city = build_system_prompt("loc", region_type="city")
        assert default == city

    def test_wilderness_prompt_includes_travel(self):
        prompt = build_system_prompt("loc", region_type="wilderness")
        assert "travel" in prompt.lower() or "wilderness" in prompt.lower()

    def test_wilderness_prompt_has_no_commerce_rule(self):
        from prompts import WILDERNESS_PROMPT

        prompt = build_system_prompt("loc", region_type="wilderness")
        assert WILDERNESS_PROMPT in prompt
        assert "No NPC commerce" in prompt

    def test_dungeon_prompt_includes_corruption(self):
        from prompts import DUNGEON_PROMPT

        prompt = build_system_prompt("loc", region_type="dungeon")
        assert DUNGEON_PROMPT in prompt
        assert "corruption" in prompt.lower()

    def test_dungeon_prompt_has_no_social_rule(self):
        prompt = build_system_prompt("loc", region_type="dungeon")
        assert "No social context" in prompt

    def test_each_region_type_has_voice_style(self):
        from prompts import VOICE_STYLE_PROMPT

        for rt in ("city", "wilderness", "dungeon"):
            prompt = build_system_prompt("loc", region_type=rt)
            assert VOICE_STYLE_PROMPT in prompt, f"{rt} prompt missing VOICE_STYLE_PROMPT"


class TestRegionTypeWarmLayer:
    """Warm layer adjusts sections by region_type."""

    @patch("db.get_npc_dispositions", new_callable=AsyncMock, return_value={"guildmaster_torin": "friendly"})
    @patch("db.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db.get_location", new_callable=AsyncMock)
    async def test_city_warm_layer_includes_npcs(self, mock_loc, mock_npcs, mock_disp):
        mock_loc.return_value = SAMPLE_LOCATION
        mock_npcs.return_value = [SAMPLE_NPC_RAW]
        result = await build_warm_layer(
            "accord_guild_hall",
            "p1",
            "evening",
            quests=[SAMPLE_QUEST],
            location=SAMPLE_LOCATION,
            npcs_raw=[SAMPLE_NPC_RAW],
            region_type="city",
        )
        assert "NPCS PRESENT" in result

    @patch("db.get_npc_dispositions", new_callable=AsyncMock, return_value={})
    @patch("db.get_npcs_at_location", new_callable=AsyncMock, return_value=[])
    @patch("db.get_location", new_callable=AsyncMock)
    async def test_wilderness_warm_layer_omits_npcs(self, mock_loc, mock_npcs, mock_disp):
        mock_loc.return_value = SAMPLE_LOCATION
        result = await build_warm_layer(
            "greyvale_south_road",
            "p1",
            "evening",
            quests=[],
            location=SAMPLE_LOCATION,
            npcs_raw=[SAMPLE_NPC_RAW],
            region_type="wilderness",
        )
        assert "NPCS PRESENT" not in result

    @patch("db.get_npc_dispositions", new_callable=AsyncMock, return_value={})
    @patch("db.get_npcs_at_location", new_callable=AsyncMock, return_value=[])
    @patch("db.get_location", new_callable=AsyncMock)
    async def test_dungeon_warm_layer_omits_npcs(self, mock_loc, mock_npcs, mock_disp):
        mock_loc.return_value = SAMPLE_LOCATION
        result = await build_warm_layer(
            "greyvale_ruins_entrance",
            "p1",
            "evening",
            quests=[],
            location=SAMPLE_LOCATION,
            npcs_raw=[SAMPLE_NPC_RAW],
            region_type="dungeon",
        )
        assert "NPCS PRESENT" not in result

    @patch("db.get_npc_dispositions", new_callable=AsyncMock, return_value={})
    @patch("db.get_npcs_at_location", new_callable=AsyncMock, return_value=[])
    @patch("db.get_location", new_callable=AsyncMock)
    async def test_dungeon_warm_layer_includes_corruption(self, mock_loc, mock_npcs, mock_disp):
        mock_loc.return_value = SAMPLE_LOCATION
        result = await build_warm_layer(
            "greyvale_ruins_inner",
            "p1",
            "evening",
            quests=[],
            location=SAMPLE_LOCATION,
            npcs_raw=[],
            corruption_level=2,
            region_type="dungeon",
        )
        assert "HOLLOW CORRUPTION" in result


class TestBuildFullPrompt:
    def test_combines_layers(self):
        result = build_full_prompt("STATIC", "WARM")
        assert "STATIC" in result
        assert "WARM" in result
        assert "---" in result

    def test_empty_warm_layer(self):
        result = build_full_prompt("STATIC", "")
        assert result == "STATIC"
