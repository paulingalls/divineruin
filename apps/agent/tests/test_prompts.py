"""Tests for prompt building (warm layer)."""

from unittest.mock import AsyncMock, patch

import pytest

from system_prompts import build_system_prompt
from warm_prompts import build_full_prompt, build_warm_layer, format_training_section

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


SAMPLE_AWAITING_TRAINING = {
    "id": "train_mid01",
    "activity_type": "technique_base",
    "state": "awaiting_decision",
    "data": {
        "program_name": "Combat Fundamentals",
        "decision_prompt": "Refine your stance: aggressive or defensive?",
        "decision_options": [
            {"id": "aggressive", "label": "Aggressive stance"},
            {"id": "defensive", "label": "Defensive stance"},
        ],
    },
}

SAMPLE_RUNNING_TRAINING = {
    "id": "train_run02",
    "activity_type": "spell_standard",
    "state": "running_first_half",
    "data": {"program_name": "Firebolt Study"},
}

SAMPLE_COMPLETE_TRAINING = {
    "id": "train_done03",
    "activity_type": "skill_practice",
    "state": "complete",
    "data": {"program_name": "Stealth Drills"},
}


class TestFormatTrainingSection:
    def test_empty_returns_none(self):
        assert format_training_section([]) is None

    def test_awaiting_decision_names_id_state_program_prompt_options(self):
        section = format_training_section([SAMPLE_AWAITING_TRAINING])
        assert section is not None
        assert section.startswith("ACTIVE TRAINING")
        # The training_id must be unambiguous so the DM can pass it to
        # resolve_training_midpoint.
        assert "train_mid01" in section
        assert "awaiting_decision" in section
        assert "Combat Fundamentals" in section
        assert "aggressive or defensive" in section
        assert "Aggressive stance" in section
        assert "aggressive" in section
        assert "Defensive stance" in section
        assert "defensive" in section

    def test_running_cycle_has_id_and_state_but_no_options(self):
        section = format_training_section([SAMPLE_RUNNING_TRAINING])
        assert section is not None
        assert "train_run02" in section
        assert "running_first_half" in section
        assert "Firebolt Study" in section
        assert "Options:" not in section

    def test_multiple_active_cycles_all_listed(self):
        section = format_training_section([SAMPLE_AWAITING_TRAINING, SAMPLE_RUNNING_TRAINING])
        assert section is not None
        assert "train_mid01" in section
        assert "train_run02" in section


class TestBuildWarmLayer:
    @patch("db_queries.get_active_player_quests", new_callable=AsyncMock)
    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
    async def test_includes_location(self, mock_loc, mock_npcs, mock_disp, mock_quests):
        mock_loc.return_value = SAMPLE_LOCATION
        mock_npcs.return_value = []
        mock_quests.return_value = []
        result = await build_warm_layer("accord_guild_hall", "player_1", "evening")
        assert "Guild Hall" in result
        assert "evening" in result

    @patch("db_queries.get_active_player_quests", new_callable=AsyncMock)
    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
    async def test_includes_npcs(self, mock_loc, mock_npcs, mock_disp, mock_quests):
        mock_loc.return_value = SAMPLE_LOCATION
        mock_npcs.return_value = [SAMPLE_NPC_RAW]
        mock_disp.return_value = {}
        mock_quests.return_value = []
        result = await build_warm_layer("accord_guild_hall", "player_1", "evening")
        assert "Guildmaster Torin" in result
        assert "neutral" in result

    @patch("db_queries.get_active_player_quests", new_callable=AsyncMock)
    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
    async def test_includes_quests(self, mock_loc, mock_npcs, mock_disp, mock_quests):
        mock_loc.return_value = SAMPLE_LOCATION
        mock_npcs.return_value = []
        mock_quests.return_value = [SAMPLE_QUEST]
        result = await build_warm_layer("accord_guild_hall", "player_1", "evening")
        assert "Greyvale Anomaly" in result
        assert "Find the source" in result

    @patch("db_queries.get_active_player_quests", new_callable=AsyncMock)
    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
    async def test_night_applies_time_conditions(self, mock_loc, mock_npcs, mock_disp, mock_quests):
        mock_loc.return_value = SAMPLE_LOCATION
        mock_npcs.return_value = []
        mock_quests.return_value = []
        result = await build_warm_layer("accord_guild_hall", "player_1", "night")
        assert "dim and quiet" in result
        assert "hushed" in result

    @patch("db_queries.get_active_player_quests", new_callable=AsyncMock)
    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
    async def test_active_training_section_appears(self, mock_loc, mock_npcs, mock_disp, mock_quests):
        mock_loc.return_value = SAMPLE_LOCATION
        mock_npcs.return_value = []
        mock_quests.return_value = []
        result = await build_warm_layer("accord_guild_hall", "player_1", "evening", training=[SAMPLE_AWAITING_TRAINING])
        assert "ACTIVE TRAINING" in result
        assert "train_mid01" in result

    @patch("db_queries.get_active_player_quests", new_callable=AsyncMock)
    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
    async def test_completed_training_omitted(self, mock_loc, mock_npcs, mock_disp, mock_quests):
        mock_loc.return_value = SAMPLE_LOCATION
        mock_npcs.return_value = []
        mock_quests.return_value = []
        result = await build_warm_layer("accord_guild_hall", "player_1", "evening", training=[SAMPLE_COMPLETE_TRAINING])
        assert "ACTIVE TRAINING" not in result


class TestBuildWarmLayerExits:
    @patch("db_queries.get_active_player_quests", new_callable=AsyncMock)
    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
    async def test_exits_appear_in_warm_layer(self, mock_loc, mock_npcs, mock_disp, mock_quests):
        mock_loc.return_value = SAMPLE_LOCATION
        mock_npcs.return_value = []
        mock_quests.return_value = []
        result = await build_warm_layer("accord_guild_hall", "player_1", "evening")
        assert "EXITS" in result
        assert "south" in result
        assert "accord_market_square" in result

    @patch("db_queries.get_active_player_quests", new_callable=AsyncMock)
    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
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

    @patch("db_queries.get_active_player_quests", new_callable=AsyncMock)
    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
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
        from system_prompts import WILDERNESS_PROMPT

        prompt = build_system_prompt("loc", region_type="wilderness")
        assert WILDERNESS_PROMPT in prompt
        assert "No NPC commerce" in prompt

    def test_dungeon_prompt_includes_corruption(self):
        from system_prompts import DUNGEON_PROMPT

        prompt = build_system_prompt("loc", region_type="dungeon")
        assert DUNGEON_PROMPT in prompt
        assert "corruption" in prompt.lower()

    def test_dungeon_prompt_has_no_social_rule(self):
        prompt = build_system_prompt("loc", region_type="dungeon")
        assert "No social context" in prompt

    def test_each_region_type_has_voice_style(self):
        from system_prompts import VOICE_STYLE_PROMPT

        for rt in ("city", "wilderness", "dungeon"):
            prompt = build_system_prompt("loc", region_type=rt)
            assert VOICE_STYLE_PROMPT in prompt, f"{rt} prompt missing VOICE_STYLE_PROMPT"


class TestPromptToolConsistency:
    """A gameplay agent's assembled prompt must name the danger mechanics only when
    the agent actually holds them — otherwise the DM is told to call an absent tool
    (concern b1591cb23262). Enforced by construction so the next prompt edit can't
    silently reintroduce the drift (concern df5cc73b2473)."""

    @pytest.mark.parametrize("danger_tool_name", ["request_attack", "request_saving_throw"])
    def test_danger_tool_named_iff_in_toolset(self, danger_tool_name):
        from check_tools import request_attack, request_saving_throw
        from city_agent import CITY_TOOLS
        from combat_agent import COMBAT_AGENT_TOOLS
        from dispatch_agent import DISPATCH_TOOLS
        from dungeon_agent import DUNGEON_TOOLS
        from system_prompts import COMBAT_SYSTEM_PROMPT, DISPATCH_SYSTEM_PROMPT
        from wilderness_agent import WILDERNESS_TOOLS

        tool_obj = {"request_attack": request_attack, "request_saving_throw": request_saving_throw}[danger_tool_name]
        agents = {
            "city": (build_system_prompt("loc", region_type="city"), CITY_TOOLS),
            "wilderness": (build_system_prompt("loc", region_type="wilderness"), WILDERNESS_TOOLS),
            "dungeon": (build_system_prompt("loc", region_type="dungeon"), DUNGEON_TOOLS),
            "combat": (COMBAT_SYSTEM_PROMPT, COMBAT_AGENT_TOOLS),
            "training": (DISPATCH_SYSTEM_PROMPT, DISPATCH_TOOLS),
        }
        for name, (prompt, tools) in agents.items():
            named = danger_tool_name in prompt
            has_tool = tool_obj in tools
            assert named == has_tool, (
                f"{name} agent: prompt names {danger_tool_name}={named} but has the tool={has_tool}"
            )

    def test_query_info_consolidation_consistency(self):
        """After collapsing query_* into query_info: a prompt naming query_info must hold
        it (no absent-tool instruction), and no prompt may name a removed query_* tool."""
        from city_agent import CITY_TOOLS
        from combat_agent import COMBAT_AGENT_TOOLS
        from dispatch_agent import DISPATCH_TOOLS
        from dungeon_agent import DUNGEON_TOOLS
        from onboarding_agent import ONBOARDING_SYSTEM_PROMPT, ONBOARDING_TOOLS
        from query_tools import query_info
        from system_prompts import COMBAT_SYSTEM_PROMPT, DISPATCH_SYSTEM_PROMPT
        from wilderness_agent import WILDERNESS_TOOLS

        agents = {
            "city": (build_system_prompt("loc", region_type="city"), CITY_TOOLS),
            "wilderness": (build_system_prompt("loc", region_type="wilderness"), WILDERNESS_TOOLS),
            "dungeon": (build_system_prompt("loc", region_type="dungeon"), DUNGEON_TOOLS),
            "combat": (COMBAT_SYSTEM_PROMPT, COMBAT_AGENT_TOOLS),
            "training": (DISPATCH_SYSTEM_PROMPT, DISPATCH_TOOLS),
            "onboarding": (ONBOARDING_SYSTEM_PROMPT, ONBOARDING_TOOLS),
        }
        for name, (prompt, tools) in agents.items():
            if "query_info" in prompt:
                assert query_info in tools, f"{name} prompt names query_info but lacks the tool"
            for removed in ("query_location", "query_npc", "query_lore", "query_inventory"):
                assert removed not in prompt, f"{name} prompt still names removed tool {removed}"


class TestTrainingDiscoveryPrompt:
    """Training is a cities-only activity reached via the training hall. The city
    prompt carries a referral (lead the player to the hall), and the actual
    training tools live in DispatchAgent — so the city prompt must NOT name them."""

    def test_city_prompt_refers_to_the_training_hall(self):
        from system_prompts import TRAINING_PROMPT

        prompt = build_system_prompt("loc", region_type="city")
        assert TRAINING_PROMPT in prompt
        assert "training hall" in prompt
        # City no longer holds the training tools — the prompt must not name them.
        assert "query_training_programs" not in prompt

    def test_wilderness_prompt_omits_training_referral(self):
        from system_prompts import TRAINING_PROMPT

        prompt = build_system_prompt("loc", region_type="wilderness")
        assert TRAINING_PROMPT not in prompt
        assert "query_training_programs" not in prompt

    def test_dungeon_prompt_omits_training_referral(self):
        prompt = build_system_prompt("loc", region_type="dungeon")
        assert "query_training_programs" not in prompt


class TestRegionTypeWarmLayer:
    """Warm layer adjusts sections by region_type."""

    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock, return_value={"guildmaster_torin": "friendly"})
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
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

    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock, return_value={})
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock, return_value=[])
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
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

    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock, return_value={})
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock, return_value=[])
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
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

    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock, return_value={})
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock, return_value=[])
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
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
