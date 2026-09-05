"""Tests for prompt building (warm layer)."""

from unittest.mock import AsyncMock, patch

from prompt_fixtures import SAMPLE_LOCATION, SAMPLE_NPC_RAW, SAMPLE_QUEST

from system_prompts import build_system_prompt
from warm_prompts import build_warm_layer, format_training_section

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
        assert 'kind="discover"' in prompt
        assert "Navigation" in prompt

    def test_navigation_prompt_nudges_scene_transition_narration(self):
        # update_quest carries a quest-driven region move in response["scene_transition"];
        # the DM needs a cue to voice it, since NAVIGATION otherwise only covers move_player
        # (concern c7c8d6acb6ec).
        prompt = build_system_prompt("accord_guild_hall")
        assert "scene_transition" in prompt


# NOTE: region-specific system-prompt assertions moved to tests/test_region_register.py.
# After M7 story-002, build_system_prompt is region-agnostic — wilderness/dungeon/city
# narration flavor now rides the warm-layer Stage register (REGION_REGISTER), so the
# per-region prose is asserted there (TestWarmLayerRegionRegister), not here.


# NOTE: the training-hall referral moved from the city system prompt to the city
# REGION_REGISTER (warm layer) in M7 story-002 — asserted in
# tests/test_region_register.py::TestWarmLayerRegionRegister.test_city_location_yields_city_register.
