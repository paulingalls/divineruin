import json
from unittest.mock import patch
from uuid import uuid4

import pytest
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory

import db_queries
from check_resolution import D20Roll
from fate_tool_boundary import wrap_tool
from movement_tools import move_player
from query_tools import query_info
from scene_tools import enter_location
from travel_tools import travel

FRONT = "ashmark_corrupted_front"
STILL = "ashmark_still"
NORTH = "greyvale_wilderness_north"


@pytest.fixture(autouse=True)
def isolated_content_cache(monkeypatch):
    monkeypatch.setenv("CONTENT_CACHE_PREFIX", f"deep_ashmark_{uuid4().hex}:")


async def test_front_does_not_offer_the_still(reset_db_pool):
    h = MawlingHarness()
    try:
        await h.prepare((18, 18), companion=None, location=FRONT)
        assert (await h.command(enter_location.id, {"location_id": FRONT}))["still"] is None
        result = await h.command(query_info.id, {"kind": "creature"})
        entries = {entry["id"] for entry in result["encounter_templates"]}
        assert entries and "hollow_still" not in entries
    finally:
        await h.close()


async def test_enter_the_still_through_its_scene(reset_db_pool):
    h = MawlingHarness()
    try:
        await h.prepare((18, 18), companion=None, location=FRONT, tools=(move_player,))
        front = await h.command(enter_location.id, {"location_id": FRONT})
        destination = front["location"]["exits"]["northwest"]["destination"]
        with patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(20)):
            moved = await h.command(move_player.id, {"destination_id": destination})
            assert moved["moved"] and moved["location"]["id"] == STILL
            back = moved["location"]["exits"]["southeast"]["destination"]
            returned = await h.command(move_player.id, {"destination_id": back})
            assert returned["moved"] and returned["location"]["id"] == FRONT
            assert (await h.command(move_player.id, {"destination_id": destination}))["moved"]
        for pid in h.players:
            row = await db_queries.get_player(pid)
            assert row is not None and row["location_id"] == STILL
        scene = await h.command(enter_location.id, {"location_id": destination})
        assert "Birdsong" in scene["location"]["description"] and "brook" in scene["location"]["description"]
        entry = scene["still"]
        assert entry and entry["encounter_id"] == "hollow_still"
        assert entry["entry"] == f'enter_mode(mode="combat", encounter_id="{entry["encounter_id"]}")'
        await h.command("enter_mode", {"mode": "combat", "encounter_id": entry["encounter_id"]})
        state = await h.reload()
        assert (state.location_id, state.encounter_id) == (STILL, entry["encounter_id"])
        assert state.still_encounter is not None
        assert len(set(state.still_encounter["anchor_ids"])) == 6
    finally:
        await h.close()


@pytest.mark.parametrize("tool", [move_player, travel], ids=["move", "travel"])
async def test_party_level_warnings(reset_db_pool, tool):
    h = MawlingHarness()
    cases = [
        ((10, 10), NORTH, FRONT, 14, "arrived"),
        ((10, 10), FRONT, STILL, 18, "arrived"),
        ((11, 11), NORTH, FRONT, 14, "arrived"),
        ((11, 12), NORTH, FRONT, None, "arrived"),
        ((14, 14), NORTH, FRONT, None, "arrived"),
        ((10, 10), FRONT, NORTH, None, "arrived"),
        ((18, 5), NORTH, FRONT, None, "arrived"),
        ((15, 15), FRONT, STILL, 18, "arrived"),
    ]
    if tool is travel:
        cases.extend([((10, 10), NORTH, FRONT, 14, "held"), ((10, 10), NORTH, FRONT, 14, "lost")])
    try:
        await h.prepare((10, 10), companion=None, location=NORTH, tools=(wrap_tool(tool),))
        for levels, origin, destination, recommended, outcome in cases:
            h.sd.location_id = origin
            for pid, level in zip(h.players, levels, strict=True):
                row = await db_queries.get_player(pid)
                assert row is not None
                row.update(level=level, location_id=origin, flags={})
                if pid == h.players[0]:
                    row["divine_favor"] = (
                        {"patron": "zhael", "level": 0, "max": 100, "last_whisper_level": 0}
                        if outcome == "held"
                        else {}
                    )
                await h.pool.execute("UPDATE players SET data=$2::jsonb WHERE player_id=$1", pid, json.dumps(row))
            args = {"destination_id": destination}
            if tool is travel:
                args.update(mode="compressed", hours=1)
            face = 1 if outcome == "lost" else 20
            with patch.object(D20Roll, "roll", lambda self, _rng=None, face=face: self.evaluate(face)):
                result = await h.command(tool.id, args)
            if outcome == "held":
                assert "fate_offer" in result and h.sd.location_id == origin
                assert f"level {recommended}" in result.get("level_warning", "")
                result = (await h.command(query_info.id, {"kind": "inventory"}))["settled_fate"]
            if outcome == "lost":
                assert result["wrong_area"] and not result["arrived"]
            else:
                assert result.get("moved", result.get("arrived"))
            if recommended is None:
                assert "level_warning" not in result
            else:
                assert f"level {recommended}" in result.get("level_warning", "")
    finally:
        await h.close()


@pytest.mark.parametrize("tool", [move_player, travel], ids=["move", "travel"])
def test_warning_precedes_arrival_narration(tool):
    description = tool.info.description
    assert "level_warning" in description
    assert "voice it before narrating arrival" in description
