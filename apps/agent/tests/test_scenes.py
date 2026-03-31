"""Tests for scene/play-tree resolution and transitions (H.6)."""

from __future__ import annotations

import json
import pathlib
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from prompts import build_warm_layer
from session_data import SessionData
from tools import detect_scene_transition, get_active_scene, update_quest

# --- Shared test fixtures ---

QUEST_WITH_SCENES: dict = {
    "id": "test_quest",
    "name": "Test Quest",
    "stages": [
        {"id": "s0", "objective": "Go somewhere"},
        {"id": "s1", "objective": "Talk to someone"},
        {"id": "s2", "objective": "Fight something"},
        {"id": "s3", "objective": "Explore ruins"},
        {"id": "s4", "objective": "Return home"},
    ],
    "scenes": [
        {
            "id": "scene_road",
            "name": "Road to Millhaven",
            "region_type": "wilderness",
            "instructions": "Atmospheric travel narration.",
            "stage_refs": [0],
        },
        {
            "id": "scene_city",
            "name": "Millhaven Investigation",
            "region_type": "city",
            "instructions": "Investigation and NPC focus.",
            "stage_refs": [1],
        },
        {
            "id": "scene_combat",
            "name": "First Hollow Encounter",
            "region_type": "wilderness",
            "instructions": "Tense pre-combat atmosphere.",
            "stage_refs": [2],
        },
        {
            "id": "scene_ruins",
            "name": "Ruins Exploration",
            "region_type": "dungeon",
            "instructions": "Dark, oppressive dungeon crawl.",
            "stage_refs": [3],
        },
        {
            "id": "scene_return",
            "name": "Return to Accord",
            "region_type": "city",
            "instructions": "Reflective journey home.",
            "stage_refs": [4],
        },
    ],
}

QUEST_WITH_MULTI_STAGE_SCENE: dict = {
    "id": "multi_quest",
    "name": "Multi Stage Quest",
    "stages": [
        {"id": "s0", "objective": "A"},
        {"id": "s1", "objective": "B"},
        {"id": "s2", "objective": "C"},
    ],
    "scenes": [
        {
            "id": "scene_ab",
            "name": "Combined Scene",
            "region_type": "city",
            "instructions": "Covers two stages.",
            "stage_refs": [0, 1],
        },
        {
            "id": "scene_c",
            "name": "Final Scene",
            "region_type": "wilderness",
            "instructions": "Last part.",
            "stage_refs": [2],
        },
    ],
}

QUEST_WITHOUT_SCENES: dict = {
    "id": "plain_quest",
    "name": "Plain Quest",
    "stages": [{"id": "s0", "objective": "Do stuff"}],
}


# === get_active_scene ===


class TestGetActiveScene:
    def test_returns_matching_scene(self):
        scene = get_active_scene(QUEST_WITH_SCENES, 0)
        assert scene is not None
        assert scene["id"] == "scene_road"
        assert scene["region_type"] == "wilderness"

    def test_returns_correct_scene_for_each_stage(self):
        assert get_active_scene(QUEST_WITH_SCENES, 1)["id"] == "scene_city"
        assert get_active_scene(QUEST_WITH_SCENES, 2)["id"] == "scene_combat"
        assert get_active_scene(QUEST_WITH_SCENES, 3)["id"] == "scene_ruins"
        assert get_active_scene(QUEST_WITH_SCENES, 4)["id"] == "scene_return"

    def test_no_scenes_returns_none(self):
        assert get_active_scene(QUEST_WITHOUT_SCENES, 0) is None

    def test_stage_beyond_all_scenes_returns_none(self):
        assert get_active_scene(QUEST_WITH_SCENES, 99) is None

    def test_negative_stage_returns_none(self):
        assert get_active_scene(QUEST_WITH_SCENES, -1) is None

    def test_multi_stage_ref(self):
        scene_at_0 = get_active_scene(QUEST_WITH_MULTI_STAGE_SCENE, 0)
        scene_at_1 = get_active_scene(QUEST_WITH_MULTI_STAGE_SCENE, 1)
        assert scene_at_0 is not None
        assert scene_at_0["id"] == "scene_ab"
        assert scene_at_1 is not None
        assert scene_at_1["id"] == "scene_ab"

    def test_empty_quest_dict(self):
        assert get_active_scene({}, 0) is None


# === detect_scene_transition ===


class TestDetectSceneTransition:
    def test_same_scene_returns_none(self):
        result = detect_scene_transition(QUEST_WITH_MULTI_STAGE_SCENE, 0, 1)
        assert result is None

    def test_scene_changed_different_region(self):
        # wilderness (scene_road, stage 0) → city (scene_city, stage 1)
        result = detect_scene_transition(QUEST_WITH_SCENES, 0, 1)
        assert result is not None
        assert result["old_scene"]["id"] == "scene_road"
        assert result["new_scene"]["id"] == "scene_city"
        assert result["region_changed"] is True

    def test_scene_changed_same_region(self):
        # city (scene_city, stage 1) → wilderness (scene_combat, stage 2)
        # Actually these are different regions. Let's use multi_stage quest:
        # scene_ab (city, [0,1]) → scene_c (wilderness, [2]) — different region
        # We need a test with same region. Create inline:
        quest = {
            "id": "q",
            "stages": [{"id": "s0"}, {"id": "s1"}],
            "scenes": [
                {"id": "a", "name": "A", "region_type": "city", "instructions": "x", "stage_refs": [0]},
                {"id": "b", "name": "B", "region_type": "city", "instructions": "y", "stage_refs": [1]},
            ],
        }
        result = detect_scene_transition(quest, 0, 1)
        assert result is not None
        assert result["old_scene"]["id"] == "a"
        assert result["new_scene"]["id"] == "b"
        assert result["region_changed"] is False

    def test_quest_start_returns_none(self):
        # old_stage -1 means quest just started — no transition
        result = detect_scene_transition(QUEST_WITH_SCENES, -1, 0)
        assert result is None

    def test_no_scenes_returns_none(self):
        result = detect_scene_transition(QUEST_WITHOUT_SCENES, 0, 1)
        assert result is None

    def test_old_scene_none_returns_none(self):
        # If old_stage doesn't map to any scene, no transition
        result = detect_scene_transition(QUEST_WITH_SCENES, 99, 0)
        assert result is None

    def test_new_scene_none_returns_none(self):
        # If new_stage doesn't map to any scene, no transition
        result = detect_scene_transition(QUEST_WITH_SCENES, 0, 99)
        assert result is None

    def test_dungeon_to_city_transition(self):
        # dungeon (scene_ruins, stage 3) → city (scene_return, stage 4)
        result = detect_scene_transition(QUEST_WITH_SCENES, 3, 4)
        assert result is not None
        assert result["old_scene"]["region_type"] == "dungeon"
        assert result["new_scene"]["region_type"] == "city"
        assert result["region_changed"] is True


# === Greyvale quest content validation ===

CONTENT_DIR = pathlib.Path(__file__).resolve().parents[3] / "content"


class TestGreyvaleScenes:
    """Validate the authored Greyvale play tree in quests.json."""

    @classmethod
    def setup_class(cls):
        with open(CONTENT_DIR / "quests.json") as f:
            quests = json.load(f)
        cls.greyvale = next(q for q in quests if q["id"] == "greyvale_anomaly")

    def test_scenes_array_exists(self):
        assert "scenes" in self.greyvale
        assert len(self.greyvale["scenes"]) == 5

    def test_all_stages_covered(self):
        all_refs = []
        for scene in self.greyvale["scenes"]:
            all_refs.extend(scene["stage_refs"])
        assert sorted(all_refs) == [0, 1, 2, 3, 4]

    def test_each_scene_has_required_fields(self):
        for scene in self.greyvale["scenes"]:
            assert "id" in scene
            assert "name" in scene
            assert "region_type" in scene
            assert scene["region_type"] in ("city", "wilderness", "dungeon")
            assert "instructions" in scene
            assert len(scene["instructions"]) > 0
            assert "stage_refs" in scene
            assert len(scene["stage_refs"]) > 0

    def test_scene_region_types_match_expected(self):
        expected = ["wilderness", "city", "wilderness", "dungeon", "city"]
        actual = [s["region_type"] for s in self.greyvale["scenes"]]
        assert actual == expected

    def test_each_scene_has_beats(self):
        for scene in self.greyvale["scenes"]:
            beats = scene.get("beats", [])
            assert len(beats) >= 2, f"Scene {scene['id']} needs at least 2 beats"
            for beat in beats:
                assert "id" in beat
                assert "description" in beat
                assert "completion_condition" in beat
                assert "companion_hints" in beat
                assert len(beat["companion_hints"]) >= 1
                assert "hint_delay_seconds" in beat

    def test_get_active_scene_resolves_all_stages(self):
        for stage_idx in range(5):
            scene = get_active_scene(self.greyvale, stage_idx)
            assert scene is not None, f"No scene for stage {stage_idx}"


# === Warm layer scene injection ===

SAMPLE_LOCATION = {
    "id": "accord_guild_hall",
    "name": "Guild Hall",
    "description": "Heavy oak doors open onto a hall.",
    "atmosphere": "busy, purposeful",
    "key_features": ["the main counter"],
    "hidden_elements": [],
    "exits": {"south": {"destination": "accord_market_square"}},
    "tags": ["guild"],
}

QUEST_WITH_SCENES_FOR_WARM = {
    "quest_id": "greyvale_anomaly",
    "quest_name": "The Greyvale Anomaly",
    "current_stage": 0,
    "stages": [{"id": "s0", "objective": "Travel to Millhaven."}],
    "global_hints": {},
    "scenes": [
        {
            "id": "scene_road",
            "name": "Road to Millhaven",
            "region_type": "wilderness",
            "instructions": "Narrate the journey with growing unease.",
            "stage_refs": [0],
        },
    ],
}

QUEST_WITHOUT_SCENES_FOR_WARM = {
    "quest_id": "plain_quest",
    "quest_name": "Plain Quest",
    "current_stage": 0,
    "stages": [{"id": "s0", "objective": "Do stuff."}],
    "global_hints": {},
}


class TestWarmLayerSceneInjection:
    @pytest.mark.asyncio
    @patch("db.get_active_player_quests", new_callable=AsyncMock)
    @patch("db.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db.get_location", new_callable=AsyncMock)
    async def test_includes_scene_instructions(self, mock_loc, mock_npcs, mock_quests):
        mock_loc.return_value = SAMPLE_LOCATION
        mock_npcs.return_value = []
        mock_quests.return_value = [QUEST_WITH_SCENES_FOR_WARM]
        result = await build_warm_layer("accord_guild_hall", "player_1", "evening")
        assert "ACTIVE SCENE" in result
        assert "Road to Millhaven" in result
        assert "Narrate the journey with growing unease." in result

    @pytest.mark.asyncio
    @patch("db.get_active_player_quests", new_callable=AsyncMock)
    @patch("db.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db.get_location", new_callable=AsyncMock)
    async def test_no_scene_section_without_scenes(self, mock_loc, mock_npcs, mock_quests):
        mock_loc.return_value = SAMPLE_LOCATION
        mock_npcs.return_value = []
        mock_quests.return_value = [QUEST_WITHOUT_SCENES_FOR_WARM]
        result = await build_warm_layer("accord_guild_hall", "player_1", "evening")
        assert "ACTIVE SCENE" not in result

    @pytest.mark.asyncio
    @patch("db.get_active_player_quests", new_callable=AsyncMock)
    @patch("db.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db.get_location", new_callable=AsyncMock)
    async def test_no_scene_section_with_empty_quests(self, mock_loc, mock_npcs, mock_quests):
        mock_loc.return_value = SAMPLE_LOCATION
        mock_npcs.return_value = []
        mock_quests.return_value = []
        result = await build_warm_layer("accord_guild_hall", "player_1", "evening")
        assert "ACTIVE SCENE" not in result


# === update_quest scene-triggered handoffs ===

QUEST_WITH_SCENES_FOR_HANDOFF: dict = {
    "id": "scene_quest",
    "name": "Scene Quest",
    "stages": [
        {"id": "s0", "objective": "Travel.", "on_complete": {}},
        {"id": "s1", "objective": "Investigate.", "on_complete": {}},
        {"id": "s2", "objective": "Fight.", "on_complete": {}},
    ],
    "scenes": [
        {
            "id": "scene_wild",
            "name": "Wilderness Scene",
            "region_type": "wilderness",
            "instructions": "Travel narration.",
            "stage_refs": [0],
        },
        {
            "id": "scene_city",
            "name": "City Scene",
            "region_type": "city",
            "instructions": "City narration.",
            "stage_refs": [1],
        },
        {
            "id": "scene_wild2",
            "name": "Wilderness Again",
            "region_type": "wilderness",
            "instructions": "Back to wilderness.",
            "stage_refs": [2],
        },
    ],
}

QUEST_NO_SCENES_FOR_HANDOFF: dict = {
    "id": "plain_quest",
    "name": "Plain Quest",
    "stages": [
        {"id": "s0", "objective": "A.", "on_complete": {}},
        {"id": "s1", "objective": "B.", "on_complete": {}},
    ],
}

_mock_conn = MagicMock(name="mock_txn_conn")


@asynccontextmanager
async def _mock_transaction():
    yield _mock_conn


def _make_context(player_id="player_1", location_id="accord_guild_hall"):
    ctx = MagicMock()
    ctx.userdata = SessionData(player_id=player_id, location_id=location_id)
    return ctx


@patch("tools.db.transaction", _mock_transaction)
class TestUpdateQuestSceneHandoff:
    @pytest.mark.asyncio
    @patch("tools.db.set_player_quest", new_callable=AsyncMock)
    @patch("tools.db.get_player_quest", new_callable=AsyncMock)
    @patch("tools.db.get_quest", new_callable=AsyncMock)
    async def test_region_change_returns_agent_tuple(self, mock_quest, mock_pq, mock_set):
        """Advancing from wilderness scene to city scene returns (agent, json)."""
        mock_quest.return_value = QUEST_WITH_SCENES_FOR_HANDOFF
        mock_pq.return_value = {"current_stage": 0}
        ctx = _make_context()
        result = await update_quest._func(ctx, quest_id="scene_quest", new_stage_id=1)
        assert isinstance(result, tuple), f"Expected tuple, got {type(result)}"
        agent, json_str = result
        from gameplay_agent import GameplayAgent

        assert isinstance(agent, GameplayAgent)
        assert agent._agent_type == "city"
        parsed = json.loads(json_str)
        assert parsed["new_stage"] == 1

    @pytest.mark.asyncio
    @patch("tools.db.set_player_quest", new_callable=AsyncMock)
    @patch("tools.db.get_player_quest", new_callable=AsyncMock)
    @patch("tools.db.get_quest", new_callable=AsyncMock)
    async def test_same_region_returns_string(self, mock_quest, mock_pq, mock_set):
        """Advancing within same region type returns plain json string."""
        quest = {
            "id": "q",
            "name": "Q",
            "stages": [
                {"id": "s0", "objective": "A.", "on_complete": {}},
                {"id": "s1", "objective": "B.", "on_complete": {}},
            ],
            "scenes": [
                {"id": "a", "name": "A", "region_type": "city", "instructions": "x", "stage_refs": [0]},
                {"id": "b", "name": "B", "region_type": "city", "instructions": "y", "stage_refs": [1]},
            ],
        }
        mock_quest.return_value = quest
        mock_pq.return_value = {"current_stage": 0}
        ctx = _make_context()
        result = await update_quest._func(ctx, quest_id="q", new_stage_id=1)
        assert isinstance(result, str), f"Expected str, got {type(result)}"
        parsed = json.loads(result)
        assert parsed["new_stage"] == 1

    @pytest.mark.asyncio
    @patch("tools.db.set_player_quest", new_callable=AsyncMock)
    @patch("tools.db.get_player_quest", new_callable=AsyncMock)
    @patch("tools.db.get_quest", new_callable=AsyncMock)
    async def test_no_scenes_returns_string(self, mock_quest, mock_pq, mock_set):
        """Quest without scenes returns plain json string (backward compat)."""
        mock_quest.return_value = QUEST_NO_SCENES_FOR_HANDOFF
        mock_pq.return_value = {"current_stage": 0}
        ctx = _make_context()
        result = await update_quest._func(ctx, quest_id="plain_quest", new_stage_id=1)
        assert isinstance(result, str), f"Expected str, got {type(result)}"
        parsed = json.loads(result)
        assert parsed["new_stage"] == 1

    @pytest.mark.asyncio
    @patch("tools.db.set_player_quest", new_callable=AsyncMock)
    @patch("tools.db.get_player_quest", new_callable=AsyncMock)
    @patch("tools.db.get_quest", new_callable=AsyncMock)
    async def test_quest_start_no_handoff(self, mock_quest, mock_pq, mock_set):
        """Starting a quest (stage -1 → 0) never triggers a handoff."""
        mock_quest.return_value = QUEST_WITH_SCENES_FOR_HANDOFF
        mock_pq.return_value = None  # quest not started yet
        ctx = _make_context()
        result = await update_quest._func(ctx, quest_id="scene_quest", new_stage_id=0)
        assert isinstance(result, str), f"Expected str on quest start, got {type(result)}"
