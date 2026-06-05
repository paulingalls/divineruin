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
        # §7: ungated exits are `go` affordances.
        assert "go:" in result
        assert "south" in result
        assert "accord_market_square" in result

    @patch("db_queries.get_player_flag", new_callable=AsyncMock)
    @patch("db_queries.get_active_player_quests", new_callable=AsyncMock)
    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
    async def test_blocked_exit_shows_locked_without_leaking_requires(
        self, mock_loc, mock_npcs, mock_disp, mock_quests, mock_flag
    ):
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
        mock_flag.return_value = False  # requirement unmet -> exit stays locked
        result = await build_warm_layer("accord_guild_hall", "player_1", "evening")
        # §7: a gated exit renders under `check` as "(locked)", until unlocked — but the raw
        # `requires` string (flag names / undiscovered hidden ids) never reaches the DM layer.
        assert "check:" in result
        assert "east (locked)" in result
        assert "temple_key" not in result

    @patch("db_queries.get_player_flag", new_callable=AsyncMock)
    @patch("db_queries.get_active_player_quests", new_callable=AsyncMock)
    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
    async def test_blocked_exit_uses_blocked_hint_when_present(
        self, mock_loc, mock_npcs, mock_disp, mock_quests, mock_flag
    ):
        # When content gives a DM-safe blocked_hint, the locked label surfaces it (still no
        # raw requires).
        location_with_hint = {
            **SAMPLE_LOCATION,
            "exits": {
                "east": {
                    "destination": "accord_temple_row",
                    "requires": "temple_key",
                    "blocked_hint": "a sealed bronze door bars the way",
                },
            },
        }
        mock_loc.return_value = location_with_hint
        mock_npcs.return_value = []
        mock_quests.return_value = []
        mock_flag.return_value = False
        result = await build_warm_layer("accord_guild_hall", "player_1", "evening")
        assert "east (locked: a sealed bronze door bars the way)" in result
        assert "temple_key" not in result

    @patch("db_queries.get_player_flag", new_callable=AsyncMock)
    @patch("db_queries.get_active_player_quests", new_callable=AsyncMock)
    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
    async def test_met_requirement_promotes_exit_check_to_go(
        self, mock_loc, mock_npcs, mock_disp, mock_quests, mock_flag
    ):
        # §7 (story-004): once the requirement is MET, the gated exit promotes check -> go.
        location_with_gate = {
            **SAMPLE_LOCATION,
            "exits": {
                "south": {"destination": "accord_market_square"},
                "east": {"destination": "accord_temple_row", "requires": "temple_key"},
            },
        }
        mock_loc.return_value = location_with_gate
        mock_npcs.return_value = []
        mock_quests.return_value = []
        mock_flag.return_value = True  # player holds the flag -> requirement met
        result = await build_warm_layer("accord_guild_hall", "player_1", "evening")
        assert "east → accord_temple_row" in result  # now a go affordance
        assert "east (locked" not in result

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

    @patch("db_queries.get_active_player_quests", new_callable=AsyncMock)
    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock)
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
    async def test_danger_rendered_as_band_not_integer(self, mock_loc, mock_npcs, mock_disp, mock_quests):
        # §7: numbers stay in engine/HUD; the voiced warm layer speaks the danger BAND.
        mock_loc.return_value = {**SAMPLE_LOCATION, "danger_level": 2}
        mock_npcs.return_value = []
        mock_quests.return_value = []
        result = await build_warm_layer("accord_guild_hall", "player_1", "evening")
        assert "danger: dangerous" in result
        assert "danger: 2" not in result
        assert "AFFORDANCES" in result


class TestNavigationPromptIncluded:
    def test_system_prompt_includes_navigation(self):
        prompt = build_system_prompt("accord_guild_hall")
        assert 'mode="discover"' in prompt
        assert "Navigation" in prompt


# NOTE: region-specific system-prompt assertions moved to tests/test_region_register.py.
# After M7 story-002, build_system_prompt is region-agnostic — wilderness/dungeon/city
# narration flavor now rides the warm-layer Stage register (REGION_REGISTER), so the
# per-region prose is asserted there (TestWarmLayerRegionRegister), not here.


class TestPromptToolConsistency:
    """A gameplay agent's assembled prompt must name the danger mechanics only when
    the agent actually holds them — otherwise the DM is told to call an absent tool
    (concern b1591cb23262). Enforced by construction so the next prompt edit can't
    silently reintroduce the drift (concern df5cc73b2473)."""

    @pytest.mark.parametrize("danger_tool_name", ["request_attack"])
    def test_danger_tool_named_iff_in_toolset(self, danger_tool_name):
        # request_saving_throw folded into the universal `check` verb (M5 story-003), so
        # request_attack is the remaining combat-only danger tool that must not appear in a
        # prompt unless the agent holds it.
        from check_tools import request_attack
        from combat_agent import COMBAT_AGENT_TOOLS
        from dispatch_agent import DISPATCH_TOOLS
        from exploration_agent import EXPLORATION_TOOLS
        from system_prompts import COMBAT_SYSTEM_PROMPT, DISPATCH_SYSTEM_PROMPT

        tool_obj = {"request_attack": request_attack}[danger_tool_name]
        agents = {
            "exploration": (build_system_prompt("loc"), EXPLORATION_TOOLS),
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
        from combat_agent import COMBAT_AGENT_TOOLS
        from dispatch_agent import DISPATCH_TOOLS
        from exploration_agent import EXPLORATION_TOOLS
        from mode_tools import enter_mode
        from onboarding_agent import ONBOARDING_SYSTEM_PROMPT, ONBOARDING_TOOLS
        from query_tools import query_info
        from system_prompts import COMBAT_SYSTEM_PROMPT, DISPATCH_SYSTEM_PROMPT

        agents = {
            "exploration": (build_system_prompt("loc"), EXPLORATION_TOOLS),
            "combat": (COMBAT_SYSTEM_PROMPT, COMBAT_AGENT_TOOLS),
            "training": (DISPATCH_SYSTEM_PROMPT, DISPATCH_TOOLS),
            "onboarding": (ONBOARDING_SYSTEM_PROMPT, ONBOARDING_TOOLS),
        }
        for name, (prompt, tools) in agents.items():
            if "query_info" in prompt:
                assert query_info in tools, f"{name} prompt names query_info but lacks the tool"
            for removed in ("query_location", "query_npc", "query_lore", "query_inventory"):
                assert removed not in prompt, f"{name} prompt still names removed tool {removed}"
            # enter_mode named iff held (region agents hold + name it; others neither).
            assert ("enter_mode" in prompt) == (enter_mode in tools), (
                f"{name}: prompt names enter_mode but tool-holding differs"
            )


# NOTE: the training-hall referral moved from the city system prompt to the city
# REGION_REGISTER (warm layer) in M7 story-002 — asserted in
# tests/test_region_register.py::TestWarmLayerRegionRegister.test_city_location_yields_city_register.


class TestRegionTypeWarmLayer:
    """Warm layer adjusts sections by region_type."""

    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock, return_value={"guildmaster_torin": "friendly"})
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
    async def test_city_warm_layer_includes_npcs(self, mock_loc, mock_npcs, mock_disp):
        city_loc = {**SAMPLE_LOCATION, "region_type": "city"}
        mock_loc.return_value = city_loc
        mock_npcs.return_value = [SAMPLE_NPC_RAW]
        result = await build_warm_layer(
            "accord_guild_hall",
            "p1",
            "evening",
            quests=[SAMPLE_QUEST],
            location=city_loc,
            npcs_raw=[SAMPLE_NPC_RAW],
        )
        # §7: NPCs present are `address` affordances (gate sourced from the Stage region_type).
        assert "address:" in result

    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock, return_value={})
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock, return_value=[])
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
    async def test_wilderness_warm_layer_omits_npcs(self, mock_loc, mock_npcs, mock_disp):
        wild_loc = {**SAMPLE_LOCATION, "region_type": "wilderness"}
        mock_loc.return_value = wild_loc
        result = await build_warm_layer(
            "greyvale_south_road",
            "p1",
            "evening",
            quests=[],
            location=wild_loc,
            npcs_raw=[SAMPLE_NPC_RAW],
        )
        # Wilderness Stage: no commerce gate, so NPCs present do NOT surface as address affordances.
        assert "address:" not in result

    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock, return_value={})
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock, return_value=[])
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
    async def test_dungeon_warm_layer_omits_npcs(self, mock_loc, mock_npcs, mock_disp):
        dungeon_loc = {**SAMPLE_LOCATION, "region_type": "dungeon"}
        mock_loc.return_value = dungeon_loc
        result = await build_warm_layer(
            "greyvale_ruins_entrance",
            "p1",
            "evening",
            quests=[],
            location=dungeon_loc,
            npcs_raw=[SAMPLE_NPC_RAW],
        )
        # Dungeon Stage: no commerce gate, so NPCs present do NOT surface as address affordances.
        assert "address:" not in result

    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock, return_value={})
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock, return_value=[])
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
    async def test_dungeon_warm_layer_includes_corruption(self, mock_loc, mock_npcs, mock_disp):
        dungeon_loc = {**SAMPLE_LOCATION, "region_type": "dungeon"}
        mock_loc.return_value = dungeon_loc
        result = await build_warm_layer(
            "greyvale_ruins_inner",
            "p1",
            "evening",
            quests=[],
            location=dungeon_loc,
            npcs_raw=[],
            corruption_level=2,
        )
        assert "HOLLOW CORRUPTION" in result


class TestGatedExitEvaluationCount:
    """Regression pin (retro try d172fa50ba56): the warm-layer affordance loop must
    evaluate _check_exit_requirement exactly ONCE per GATED exit (exit.requires set)
    and never for ungated exits — not once per turn. Warm rebuilds are event-driven,
    so this keeps the per-branch flag read off the hot path."""

    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock, return_value={})
    @patch("movement_tools._check_exit_requirement", new_callable=AsyncMock, return_value=True)
    async def test_check_exit_requirement_awaited_once_per_gated_exit(self, mock_check, _disp):
        loc = {
            **SAMPLE_LOCATION,
            "region_type": "city",
            "exits": {
                "north": {"destination": "a", "requires": "key_a.discovered"},
                "south": {"destination": "b", "requires": "key_b.discovered"},
                "east": {"destination": "c"},  # ungated — must NOT trigger an evaluation
            },
        }
        await build_warm_layer("loc", "p1", "evening", quests=[], location=loc, npcs_raw=[])
        assert mock_check.await_count == 2

    @patch("db_queries.get_npc_dispositions", new_callable=AsyncMock, return_value={})
    @patch("movement_tools._check_exit_requirement", new_callable=AsyncMock, return_value=True)
    async def test_ungated_exits_skip_evaluation(self, mock_check, _disp):
        loc = {
            **SAMPLE_LOCATION,
            "region_type": "city",
            "exits": {"east": {"destination": "c"}, "west": {"destination": "d"}},
        }
        await build_warm_layer("loc", "p1", "evening", quests=[], location=loc, npcs_raw=[])
        assert mock_check.await_count == 0


class TestBuildFullPrompt:
    def test_combines_layers(self):
        result = build_full_prompt("STATIC", "WARM")
        assert "STATIC" in result
        assert "WARM" in result
        assert "---" in result

    def test_empty_warm_layer(self):
        result = build_full_prompt("STATIC", "")
        assert result == "STATIC"
