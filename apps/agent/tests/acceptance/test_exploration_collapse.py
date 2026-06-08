"""Capstone: Milestone 7 exploration-agent collapse (story-005).

Proves the four M7 stories compose end-to-end — the Definition of Done no single
per-story test covers whole:

  - AC1: one agent's warm layer sources its REGISTER from the Stage's region_type
    (city/wilderness/dungeon), and flipping region_type flips the register —
    region and register can never disagree (story-002);
  - AC2: the strict-tool ceiling no longer binds — the unified EXPLORATION_TOOLS
    list has headroom under MAX_STRICT_TOOLS and the per-region agent classes are
    gone (story-001);
  - AC3: a region crossing keeps ONE warm agent — set_agent_region updates the
    live instance in place, no handoff (story-003);
  - AC4: select resolves in the dispatch context as well as exploration — the same
    verb object lives in both tool lists (story-004);
  - AC5: the collapse exposes the former city-superset verbs everywhere, so the
    Stage-driven NPC-presence guard (story-005) refuses update_npc_disposition for
    an NPC absent from the player's location, and allows it where the NPC is present.

AC1-AC4 are pure (no DB) and prove the collapse even when Docker is down. AC5 runs
over the seeded testcontainer DB (`reset_db_pool`) and skips cleanly otherwise.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import AsyncIterator

import pytest
from acceptance.seeds import seed_player
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_mock_room

import db
from region_types import REGION_CITY, REGION_DUNGEON, REGION_WILDERNESS

_PLAYER_ID = "player_m7_capstone"
_CITY_ID = "test_m7_city"
_WILD_ID = "test_m7_wilderness"
_DUNGEON_ID = "test_m7_dungeon"
_NPC_ID = "test_m7_clerk"

# Three Stages, one per region. Minimal — exits are ungated (no `requires`) so the warm
# layer needs no DB, keeping AC1 in the fast lane. The clerk NPC is scheduled at the city
# only, so it is "present" there and absent in the wilderness/dungeon.
_CITY = {
    "id": _CITY_ID,
    "name": "Test Market",
    "region_type": REGION_CITY,
    "danger_level": 0,
    "atmosphere": "lamplight and the murmur of trade",
    "description": "A small market square.",
    "key_features": ["a notice board"],
    "hidden_elements": [],
    "exits": {"out": {"destination": _WILD_ID}},
    "tags": ["test"],
}
_WILD = {
    **_CITY,
    "id": _WILD_ID,
    "name": "Test Road",
    "region_type": REGION_WILDERNESS,
    "atmosphere": "wind over open grass",
    "description": "An open road.",
    "exits": {"back": {"destination": _CITY_ID}, "down": {"destination": _DUNGEON_ID}},
}
_DUNGEON = {
    **_CITY,
    "id": _DUNGEON_ID,
    "name": "Test Vault",
    "region_type": REGION_DUNGEON,
    "atmosphere": "dripping water in the dark",
    "description": "A low vault.",
    "exits": {"up": {"destination": _WILD_ID}},
}
_NPC = {
    "id": _NPC_ID,
    "name": "Test Clerk",
    "role": "clerk",
    "default_disposition": "neutral",
    "schedule": {"morning": _CITY_ID, "evening": _CITY_ID},
}


async def _warm(location: dict) -> str:
    """Assemble the warm layer for one pre-fetched Stage — no NPCs, no quests, so no DB."""
    from warm_prompts import build_warm_layer

    return await build_warm_layer(
        location["id"], _PLAYER_ID, "evening", location=dict(location), npcs_raw=[], quests=[]
    )


# --- AC1: region register sourced from the Stage (pure) ---------------------------------


async def test_ac1_region_register_sourced_from_stage() -> None:
    city = await _warm(_CITY)
    wild = await _warm(_WILD)
    dungeon = await _warm(_DUNGEON)

    # The REGISTER label and its distinctive prose are keyed off each Stage's region_type.
    assert "REGISTER — Region: City" in city
    assert "training hall" in city
    assert "REGISTER — Region: Wilderness" in wild
    assert "There are no shopkeepers out here." in wild
    assert "REGISTER — Region: Dungeon" in dungeon
    assert "No commerce. No casual NPC conversation." in dungeon

    # Same location dict, flipped region_type → the register flips. Proves it reads the
    # Stage, not a caller param: region and register cannot disagree.
    flipped = await _warm({**_CITY, "region_type": REGION_DUNGEON})
    assert "REGISTER — Region: Dungeon" in flipped
    assert "There are no shopkeepers out here." not in flipped
    assert "training hall" not in flipped


# --- AC2: the strict-tool ceiling no longer binds (pure) --------------------------------


async def test_ac2_tool_ceiling_no_longer_binds() -> None:
    from exploration_agent import EXPLORATION_TOOLS
    from llm_config import MAX_STRICT_TOOLS

    # One unified list (the former city superset) with real headroom — not pinned at the
    # 20-strict-tool ceiling that drove the region split (debt e665104c753a).
    assert len(EXPLORATION_TOOLS) < MAX_STRICT_TOOLS
    assert MAX_STRICT_TOOLS - len(EXPLORATION_TOOLS) >= 5

    # The per-region agent modules are gone — collapse, not coexistence.
    for module_name in ("city_agent", "wilderness_agent", "dungeon_agent"):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(module_name)


# --- AC3: a region crossing keeps ONE warm agent (pure) ---------------------------------


async def test_ac3_region_crossing_keeps_one_warm_agent() -> None:
    from gameplay_agent import create_gameplay_agent, set_agent_region

    agent = create_gameplay_agent(REGION_CITY, _CITY_ID)
    agent_identity = id(agent)
    assert agent._agent_type == REGION_CITY

    # Crossing into the dungeon updates the live instance in place — no new agent, so the
    # cached static/system layer survives the move (movement_tools no longer hands off).
    set_agent_region(agent, REGION_DUNGEON)
    assert id(agent) == agent_identity
    assert agent._agent_type == REGION_DUNGEON


# --- AC4: select resolves across contexts (pure) ----------------------------------------


async def test_ac4_select_resolves_in_exploration_and_dispatch() -> None:
    from choice_tools import select
    from dispatch_agent import DISPATCH_TOOLS
    from exploration_agent import EXPLORATION_TOOLS

    # The same select verb object is reachable in both contexts, so an L5 fork that lands
    # mid-dispatch resolves without a handoff back to exploration.
    assert select in EXPLORATION_TOOLS
    assert select in DISPATCH_TOOLS


# --- AC5: the Stage-driven presence guard fires and doesn't over-fire (integration) -----


@pytest.fixture
async def m7_world(reset_db_pool: str) -> AsyncIterator[str]:
    """Seed the three Stages, the city-scheduled clerk, and the player; clean up after.

    Unique ids isolate the capstone from other acceptance tests on the shared session DB;
    teardown drops the seeded rows and any disposition row AC5 writes.
    """
    pool = await db.get_pool()
    await seed_player(pool, player_id=_PLAYER_ID, location_id=_CITY_ID)
    for loc in (_CITY, _WILD, _DUNGEON):
        await pool.execute(
            "INSERT INTO locations (id, data) VALUES ($1, $2::jsonb) ON CONFLICT (id) DO UPDATE SET data = $2::jsonb",
            loc["id"],
            json.dumps(loc),
        )
    await pool.execute(
        "INSERT INTO npcs (id, data) VALUES ($1, $2::jsonb) ON CONFLICT (id) DO UPDATE SET data = $2::jsonb",
        _NPC_ID,
        json.dumps(_NPC),
    )
    # db_content_queries.get_npc is Redis-cached (5-min TTL) and has no invalidation hook;
    # drop any entry left by a prior run so AC5 reads this fixture's fresh insert, not stale
    # data. Best-effort — get_npc itself falls through to the DB when Redis is unavailable.
    await _drop_npc_cache(_NPC_ID)
    try:
        yield _CITY_ID
    finally:
        await pool.execute("DELETE FROM npc_dispositions WHERE player_id = $1", _PLAYER_ID)
        await pool.execute("DELETE FROM npcs WHERE id = $1", _NPC_ID)
        await pool.execute("DELETE FROM locations WHERE id = ANY($1)", [_CITY_ID, _WILD_ID, _DUNGEON_ID])
        await pool.execute("DELETE FROM players WHERE player_id = $1", _PLAYER_ID)
        await _drop_npc_cache(_NPC_ID)


async def _drop_npc_cache(npc_id: str) -> None:
    """Best-effort delete of the get_npc cache key; tolerant of Redis being unavailable."""
    try:
        redis = await db.get_redis()
        await redis.delete(f"npc:{npc_id}")
    except Exception:
        pass


async def test_ac5_disposition_guard_blocks_absent_allows_present(m7_world: str) -> None:
    from session_tools import _update_npc_disposition_impl

    # Absent: the clerk is scheduled at the city, not the dungeon → guard refuses.
    in_dungeon = make_context(player_id=_PLAYER_ID, location_id=_DUNGEON_ID, room=make_mock_room())
    with pytest.raises(ToolError, match="isn't here"):
        await _update_npc_disposition_impl(in_dungeon, _NPC_ID, 1, "tried from afar")

    # Present: at the city (the fixture's yielded Stage) the clerk IS scheduled, so the
    # shift succeeds — the guard does not over-fire on legitimate co-located use.
    in_city = make_context(player_id=_PLAYER_ID, location_id=m7_world, room=make_mock_room())
    result = json.loads(await _update_npc_disposition_impl(in_city, _NPC_ID, 1, "helped at the stall"))
    assert result["new"] == "friendly"  # neutral default + 1
