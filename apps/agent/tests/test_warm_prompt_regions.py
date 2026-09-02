"""Region-specific warm prompt and static/warm composition tests."""

from unittest.mock import AsyncMock, patch

from warm_prompts import build_full_prompt, build_warm_layer

SAMPLE_LOCATION = {
    "id": "accord_guild_hall",
    "name": "Guild Hall",
    "description": "Heavy oak doors open onto a hall.",
    "atmosphere": "busy, purposeful",
    "key_features": ["the main counter"],
    "hidden_elements": [],
    "exits": {"south": {"destination": "accord_market_square"}},
    "tags": ["guild"],
    "conditions": {},
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
