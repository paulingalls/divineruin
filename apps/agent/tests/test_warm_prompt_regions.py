"""Region-specific warm prompt and static/warm composition tests."""

from unittest.mock import AsyncMock, patch

from prompt_fixtures import SAMPLE_LOCATION, SAMPLE_NPC_RAW, SAMPLE_QUEST, sample_combat_state

from session_data import CombatParticipant, CombatState
from warm_prompts import build_full_prompt, build_warm_layer, format_combat_hot_line


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
                "east": {"destination": "c"},
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


class TestCombatHotLine:
    """format_combat_hot_line is the per-turn combat line, rendered from combat_state alone.

    One renderer for both agents' hot layer — the warm layer carries no combat block at all.
    """

    def test_renders_round_and_each_participant_status(self):
        line = format_combat_hot_line(sample_combat_state(round_number=2, hp_current=8))
        assert line == "[COMBAT Round 2: Kael(healthy), Grosh(bloodied)]"

    def test_fallen_participant_reads_as_fallen(self):
        line = format_combat_hot_line(sample_combat_state(hp_current=0))
        assert line is not None
        assert "Grosh(fallen)" in line

    def test_none_when_not_in_combat(self):
        assert format_combat_hot_line(None) is None

    def test_zero_hp_reads_as_fallen_even_with_the_flag_unset(self):
        """The status is derived from HP, not from `is_fallen` — and the two diverge.

        combat_support.py:98 is the only site that sets `is_fallen`; draethar_inner_fire.py:91
        drives hp_current to 0 and never sets it. Deriving from HP is what keeps the DM correct
        over that gap, so this pins the derivation rather than the flag. Story-024 deleted
        TestWarmAndHotAgree (the warm/hot comparison) when the second renderer went away; this
        is what keeps the divergence named.
        """
        p = CombatParticipant(id="d", name="Draethar", type="player", initiative=10, hp_current=0, hp_max=20, ac=14)
        assert not p.is_fallen  # exactly the state draethar_inner_fire leaves behind
        cs = CombatState(combat_id="c", participants=[p], initiative_order=["d"])

        line = format_combat_hot_line(cs)
        assert line is not None
        assert "Draethar(fallen)" in line
