"""Tests for scene/play-tree resolution and transitions (H.6)."""

from __future__ import annotations

import json
import pathlib
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from session_data import SessionData
from tools import update_quest
from warm_prompts import build_warm_layer

# === Centralized scene resolution (standalone scenes) ===

SCENE_CACHE = {
    "scene_wild": {
        "id": "scene_wild",
        "name": "Wilderness Scene",
        "type": "quest",
        "region_type": "wilderness",
        "instructions": "Travel.",
        "beats": [],
    },
    "scene_city": {
        "id": "scene_city",
        "name": "City Scene",
        "type": "quest",
        "region_type": "city",
        "instructions": "Investigate.",
        "beats": [],
    },
    "scene_explore": {
        "id": "scene_explore",
        "name": "Market Exploration",
        "type": "location",
        "region_type": "city",
        "instructions": "Explore the market.",
        "beats": [],
    },
}

QUEST_WITH_GRAPH = {
    "quest_id": "greyvale",
    "quest_name": "Greyvale",
    "current_stage": 0,
    "stages": [{"id": "s0"}, {"id": "s1"}],
    "scene_graph": [
        {"scene_id": "scene_wild", "stage_refs": [0]},
        {"scene_id": "scene_city", "stage_refs": [1]},
    ],
}

QUEST_NO_GRAPH = {
    "quest_id": "plain",
    "quest_name": "Plain",
    "current_stage": 0,
    "stages": [{"id": "s0"}],
}

LOCATION_WITH_DEFAULT = {"id": "market", "default_scene": "scene_explore"}
LOCATION_NO_DEFAULT = {"id": "road"}


class TestGetActiveSceneForContext:
    def test_resolves_quest_scene_via_graph(self):
        from tools import get_active_scene_for_context

        result = get_active_scene_for_context(SCENE_CACHE, [QUEST_WITH_GRAPH], LOCATION_NO_DEFAULT)
        assert result is not None
        assert result["id"] == "scene_wild"

    def test_resolves_second_stage(self):
        from tools import get_active_scene_for_context

        quest = {**QUEST_WITH_GRAPH, "current_stage": 1}
        result = get_active_scene_for_context(SCENE_CACHE, [quest], LOCATION_NO_DEFAULT)
        assert result is not None
        assert result["id"] == "scene_city"

    def test_falls_back_to_location_default(self):
        from tools import get_active_scene_for_context

        result = get_active_scene_for_context(SCENE_CACHE, [QUEST_NO_GRAPH], LOCATION_WITH_DEFAULT)
        assert result is not None
        assert result["id"] == "scene_explore"

    def test_quest_takes_priority_over_location(self):
        from tools import get_active_scene_for_context

        result = get_active_scene_for_context(SCENE_CACHE, [QUEST_WITH_GRAPH], LOCATION_WITH_DEFAULT)
        assert result is not None
        assert result["id"] == "scene_wild"  # quest wins

    def test_returns_none_when_no_scene(self):
        from tools import get_active_scene_for_context

        result = get_active_scene_for_context(SCENE_CACHE, [QUEST_NO_GRAPH], LOCATION_NO_DEFAULT)
        assert result is None

    def test_returns_none_with_empty_cache(self):
        from tools import get_active_scene_for_context

        result = get_active_scene_for_context({}, [QUEST_WITH_GRAPH], LOCATION_WITH_DEFAULT)
        assert result is None

    def test_returns_none_with_no_quests_no_location(self):
        from tools import get_active_scene_for_context

        result = get_active_scene_for_context(SCENE_CACHE, [], LOCATION_NO_DEFAULT)
        assert result is None

    def test_missing_scene_id_in_cache_falls_through(self):
        from tools import get_active_scene_for_context

        partial_cache = {"scene_explore": SCENE_CACHE["scene_explore"]}  # no scene_wild
        result = get_active_scene_for_context(partial_cache, [QUEST_WITH_GRAPH], LOCATION_WITH_DEFAULT)
        assert result is not None
        assert result["id"] == "scene_explore"  # falls to location default


class TestDetectSceneTransition:
    def test_different_region_returns_transition(self):
        from tools import detect_scene_transition

        result = detect_scene_transition(SCENE_CACHE, QUEST_WITH_GRAPH, 0, 1)
        assert result is not None
        assert result["old_scene"]["id"] == "scene_wild"
        assert result["new_scene"]["id"] == "scene_city"
        assert result["region_changed"] is True

    def test_same_scene_returns_none(self):
        from tools import detect_scene_transition

        quest = {**QUEST_WITH_GRAPH, "scene_graph": [{"scene_id": "scene_wild", "stage_refs": [0, 1]}]}
        result = detect_scene_transition(SCENE_CACHE, quest, 0, 1)
        assert result is None

    def test_quest_start_returns_none(self):
        from tools import detect_scene_transition

        result = detect_scene_transition(SCENE_CACHE, QUEST_WITH_GRAPH, -1, 0)
        assert result is None

    def test_no_graph_returns_none(self):
        from tools import detect_scene_transition

        result = detect_scene_transition(SCENE_CACHE, QUEST_NO_GRAPH, 0, 1)
        assert result is None

    def test_missing_scene_in_cache_returns_none(self):
        from tools import detect_scene_transition

        result = detect_scene_transition({}, QUEST_WITH_GRAPH, 0, 1)
        assert result is None


# === Greyvale quest content validation ===

CONTENT_DIR = pathlib.Path(__file__).resolve().parents[3] / "content"


class TestScenesJson:
    """Validate the standalone scenes.json content file."""

    @classmethod
    def setup_class(cls):
        with open(CONTENT_DIR / "scenes.json") as f:
            cls.scenes = json.load(f)

    def test_scenes_file_is_valid(self):
        assert isinstance(self.scenes, list)
        assert len(self.scenes) >= 6  # 5 quest scenes + rider event

    def test_each_scene_has_required_fields(self):
        for scene in self.scenes:
            assert "id" in scene, "Scene missing id"
            assert "name" in scene, f"Scene {scene.get('id')} missing name"
            assert "type" in scene, f"Scene {scene['id']} missing type"
            assert scene["type"] in ("quest", "location", "event"), (
                f"Scene {scene['id']} has invalid type: {scene['type']}"
            )
            assert "region_type" in scene, f"Scene {scene['id']} missing region_type"
            assert "instructions" in scene, f"Scene {scene['id']} missing instructions"
            assert len(scene["instructions"]) > 0

    def test_scene_ids_are_unique(self):
        ids = [s["id"] for s in self.scenes]
        assert len(ids) == len(set(ids)), f"Duplicate scene IDs: {[x for x in ids if ids.count(x) > 1]}"

    def test_rider_event_scene_exists(self):
        rider = next((s for s in self.scenes if s["id"] == "scene_rider_arrival"), None)
        assert rider is not None
        assert rider["type"] == "event"
        assert "entry_conditions" in rider
        assert rider["entry_conditions"]["location"] == "accord_market_square"

    def test_quest_scenes_have_beats(self):
        quest_scenes = [s for s in self.scenes if s["type"] == "quest"]
        assert len(quest_scenes) == 5
        for scene in quest_scenes:
            assert len(scene.get("beats", [])) >= 2, f"Quest scene {scene['id']} needs >= 2 beats"

    def test_location_scenes_exist(self):
        location_scenes = [s for s in self.scenes if s["type"] == "location"]
        assert len(location_scenes) >= 2, "Need at least 2 location default scenes"

    def test_location_scenes_have_instructions(self):
        for scene in self.scenes:
            if scene["type"] == "location":
                assert len(scene["instructions"]) > 20, f"Location scene {scene['id']} needs meaningful instructions"


class TestLocationDefaultScenes:
    """Validate locations reference valid default scenes."""

    @classmethod
    def setup_class(cls):
        with open(CONTENT_DIR / "locations.json") as f:
            cls.locations = json.load(f)
        with open(CONTENT_DIR / "scenes.json") as f:
            scenes = json.load(f)
        cls.scene_ids = {s["id"] for s in scenes}

    def test_key_locations_have_default_scene(self):
        loc_map = {loc["id"]: loc for loc in self.locations}
        for loc_id in ["accord_market_square", "accord_guild_hall"]:
            assert "default_scene" in loc_map[loc_id], f"{loc_id} missing default_scene"

    def test_default_scene_ids_are_valid(self):
        for loc in self.locations:
            default = loc.get("default_scene")
            if default:
                assert default in self.scene_ids, f"Location {loc['id']} references unknown scene: {default}"


class TestGreyvaleSceneGraph:
    """Validate the Greyvale quest's scene_graph references."""

    @classmethod
    def setup_class(cls):
        with open(CONTENT_DIR / "quests.json") as f:
            quests = json.load(f)
        cls.greyvale = next(q for q in quests if q["id"] == "greyvale_anomaly")

    def test_scene_graph_exists(self):
        assert "scene_graph" in self.greyvale
        assert len(self.greyvale["scene_graph"]) == 5

    def test_scene_graph_covers_all_stages(self):
        all_refs = []
        for entry in self.greyvale["scene_graph"]:
            all_refs.extend(entry["stage_refs"])
        assert sorted(all_refs) == [0, 1, 2, 3, 4]

    def test_scene_graph_ids_exist_in_scenes_json(self):
        with open(CONTENT_DIR / "scenes.json") as f:
            scenes = json.load(f)
        scene_ids = {s["id"] for s in scenes}
        for entry in self.greyvale["scene_graph"]:
            assert entry["scene_id"] in scene_ids, f"scene_graph references unknown scene: {entry['scene_id']}"

    def test_no_embedded_scenes(self):
        assert "scenes" not in self.greyvale, "Embedded scenes should be removed — use scene_graph"


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


class TestWarmLayerSceneInjection:
    @pytest.mark.asyncio
    @patch("db_queries.get_active_player_quests", new_callable=AsyncMock)
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
    async def test_no_scene_without_cache(self, mock_loc, mock_npcs, mock_quests):
        mock_loc.return_value = SAMPLE_LOCATION
        mock_npcs.return_value = []
        mock_quests.return_value = []
        result = await build_warm_layer("accord_guild_hall", "player_1", "evening")
        assert "ACTIVE SCENE" not in result

    @pytest.mark.asyncio
    @patch("db_queries.get_npcs_at_location", new_callable=AsyncMock)
    @patch("db_content_queries.get_location", new_callable=AsyncMock)
    async def test_scene_from_scene_cache_via_graph(self, mock_loc, mock_npcs):
        """When scene_cache is provided, resolves via scene_graph."""
        mock_loc.return_value = SAMPLE_LOCATION
        mock_npcs.return_value = []
        quest_with_graph = {
            "quest_id": "greyvale",
            "quest_name": "Greyvale",
            "current_stage": 0,
            "stages": [{"id": "s0", "objective": "Travel."}],
            "scene_graph": [{"scene_id": "scene_road", "stage_refs": [0]}],
        }
        scene_cache = {
            "scene_road": {
                "id": "scene_road",
                "name": "Road to Millhaven",
                "instructions": "Narrate the journey with growing unease.",
            },
        }
        result = await build_warm_layer(
            "accord_guild_hall",
            "player_1",
            "evening",
            quests=[quest_with_graph],
            scene_cache=scene_cache,
        )
        assert "ACTIVE SCENE" in result
        assert "Road to Millhaven" in result
        assert "Narrate the journey with growing unease." in result


# === update_quest scene-triggered handoffs ===

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
    @patch("tools.db_content_queries.get_scenes_batch", new_callable=AsyncMock)
    @patch("tools.db_mutations.set_player_quest", new_callable=AsyncMock)
    @patch("tools.db_queries.get_player_quest", new_callable=AsyncMock)
    @patch("tools.db_content_queries.get_quest", new_callable=AsyncMock)
    async def test_scene_graph_handoff(self, mock_quest, mock_pq, mock_set, mock_batch):
        """Quest with scene_graph triggers handoff on region change."""
        quest = {
            "id": "graph_quest",
            "name": "Graph Quest",
            "stages": [
                {"id": "s0", "objective": "Travel.", "on_complete": {}},
                {"id": "s1", "objective": "Investigate.", "on_complete": {}},
            ],
            "scene_graph": [
                {"scene_id": "scene_wild", "stage_refs": [0]},
                {"scene_id": "scene_city", "stage_refs": [1]},
            ],
        }
        mock_quest.return_value = quest
        mock_pq.return_value = {"current_stage": 0}
        mock_batch.return_value = {
            "scene_wild": {"id": "scene_wild", "name": "Wild", "region_type": "wilderness"},
            "scene_city": {"id": "scene_city", "name": "City", "region_type": "city"},
        }
        ctx = _make_context()
        result = await update_quest._func(ctx, quest_id="graph_quest", new_stage_id=1)
        assert isinstance(result, tuple), f"Expected tuple, got {type(result)}"
        agent, _json = result
        from gameplay_agent import GameplayAgent

        assert isinstance(agent, GameplayAgent)
        assert agent._agent_type == "city"

    @pytest.mark.asyncio
    @patch("tools.db_mutations.set_player_quest", new_callable=AsyncMock)
    @patch("tools.db_queries.get_player_quest", new_callable=AsyncMock)
    @patch("tools.db_content_queries.get_quest", new_callable=AsyncMock)
    async def test_no_scene_graph_returns_string(self, mock_quest, mock_pq, mock_set):
        """Quest without scene_graph returns plain json string."""
        quest = {
            "id": "plain",
            "name": "Plain",
            "stages": [
                {"id": "s0", "objective": "A.", "on_complete": {}},
                {"id": "s1", "objective": "B.", "on_complete": {}},
            ],
        }
        mock_quest.return_value = quest
        mock_pq.return_value = {"current_stage": 0}
        ctx = _make_context()
        result = await update_quest._func(ctx, quest_id="plain", new_stage_id=1)
        assert isinstance(result, str), f"Expected str, got {type(result)}"
