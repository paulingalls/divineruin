import inspect
from unittest.mock import AsyncMock, patch

from region_types import REGION_CITY, REGION_DUNGEON, REGION_WILDERNESS
from system_prompts import build_system_prompt
from warm_prompts import build_warm_layer

BASE_LOCATION = {
    "id": "test_loc",
    "name": "Test Location",
    "description": "A plain room.",
    "atmosphere": "still",
    "key_features": [],
    "hidden_elements": [],
    "exits": {"south": {"destination": "elsewhere"}},
    "tags": [],
}


def _location(region_type: str) -> dict:
    return {**BASE_LOCATION, "region_type": region_type}


async def _warm(location: dict, *, npcs_raw=None, scene_cache=None) -> str:
    """Build the warm layer for a Stage, with no quests so the register stands alone.

    There is NO region_type param: region (and the address gate) is sourced solely
    from the location's region_type (the Stage dict) — a single source of truth.
    """
    return await build_warm_layer(
        BASE_LOCATION["id"],
        "player_1",
        "evening",
        quests=[],
        location=location,
        npcs_raw=npcs_raw or [],
        scene_cache=scene_cache,
    )


class TestSystemPromptRegionAgnostic:
    """Region flavor stays in the warm Stage register to preserve the cached static prefix."""

    def test_no_region_type_param(self):
        assert "region_type" not in inspect.signature(build_system_prompt).parameters

    def test_byte_identical_for_same_location(self):
        assert build_system_prompt("loc") == build_system_prompt("loc")

    def test_omits_region_prose(self):
        prompt = build_system_prompt("loc")
        for moved in (
            "wilderness travel",
            "dungeon exploration",
            "training hall",
            "No NPC commerce",
            "Traps and puzzles",
        ):
            assert moved not in prompt, f"region prose leaked into system prompt: {moved!r}"


@patch("db_queries.get_npc_dispositions", new_callable=AsyncMock, return_value={})
class TestWarmLayerRegionRegister:
    async def test_wilderness_location_yields_wilderness_register(self, _disp):
        result = await _warm(_location(REGION_WILDERNESS))
        assert "REGISTER — Region: Wilderness" in result
        assert "No NPC commerce" in result

    async def test_dungeon_location_yields_dungeon_register(self, _disp):
        result = await _warm(_location(REGION_DUNGEON))
        assert "REGISTER — Region: Dungeon" in result
        assert "Traps and puzzles" in result

    async def test_city_location_yields_city_register(self, _disp):
        result = await _warm(_location(REGION_CITY))
        assert "REGISTER — Region: City" in result
        assert "training hall" in result

    async def test_register_precedes_scene_register(self, _disp):
        """Put specific scene guidance after ambient region guidance so it has the final word."""
        quest = {
            "quest_id": "q",
            "quest_name": "Q",
            "current_stage": 0,
            "stages": [{"id": "s0", "objective": "go"}],
            "scene_graph": [{"scene_id": "scene_x", "stage_refs": [0]}],
        }
        scene_cache = {
            "scene_x": {"id": "scene_x", "name": "Hushed Vault", "instructions": "Speak softly."},
        }
        result = await build_warm_layer(
            BASE_LOCATION["id"],
            "player_1",
            "evening",
            quests=[quest],
            location=_location(REGION_DUNGEON),
            npcs_raw=[],
            scene_cache=scene_cache,
        )
        assert "REGISTER — Region: Dungeon" in result
        assert "REGISTER — Hushed Vault" in result
        assert result.index("REGISTER — Region: Dungeon") < result.index("REGISTER — Hushed Vault")

    async def test_region_and_address_gate_share_one_source(self, _disp):
        npc = {"id": "npc_1", "name": "Lost Miner", "role": "miner", "default_disposition": "neutral"}
        result = await _warm(_location(REGION_DUNGEON), npcs_raw=[npc])
        assert "REGISTER — Region: Dungeon" in result
        assert "address:" not in result

    async def test_city_stage_surfaces_address_gate(self, _disp):
        npc = {"id": "npc_1", "name": "Barkeep", "role": "barkeep", "default_disposition": "neutral"}
        result = await _warm(_location(REGION_CITY), npcs_raw=[npc])
        assert "REGISTER — Region: City" in result
        assert "address:" in result
