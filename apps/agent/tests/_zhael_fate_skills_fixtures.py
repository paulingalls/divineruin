import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from _patron_engine_fixtures import configure
from _zhael_fate_fixtures import defend, game_tools
from acceptance._capstone_helpers import _build_state, _enemy, _player
from test_aelora_gift import _live_party
from voice_condition_fixtures import place_actors

import db_mutations
import db_queries
from activate_tools import activate
from check_tools import check
from combat_turn import declare_phase, resolve_phase
from conditions import apply_condition
from exploration_agent import ExplorationAgent
from query_tools import query_info
from travel_tools import travel

FATE = "zhael_fates_thread"
ORIGIN = "millhaven"
DESTINATION = "greyvale_ruins_exterior"
INSPIRED = apply_condition([], "inspired")
JOURNAL = "ruins_journal_fragment"
DISCOVER = {"kind": "discover", "skill": "investigation", "target": "research station", "hearing_only": False}
SOCIAL = {
    "kind": "social",
    "synergy_context": "none",
    "skill": "persuasion",
    "npc_id": "guildmaster_torin",
    "difficulty": "easy",
}
GATHER = {"kind": "gather", "category": "herbs"}
SKILL = {
    "kind": "skill",
    "synergy_context": "none",
    "skill": "arcana",
    "difficulty": "moderate",
    "context_description": "Read the old ward",
    "hearing_only": False,
}


@pytest.fixture
async def party(world, monkeypatch):
    monkeypatch.setattr("condition_bonus.dice_roll", lambda *_args, **_kwargs: SimpleNamespace(total=1))
    session = world.ctx.userdata
    session.location_id = ORIGIN
    await configure(world, "zhael", "mage", location_id=ORIGIN, conditions=INSPIRED)
    await configure(world, "veythar", "mage", index=1, location_id=ORIGIN, flags={}, conditions=INSPIRED)
    lifecycle = _live_party(session, *world.ids)
    agent = ExplorationAgent(
        initial_location=ORIGIN,
        tools=[check, activate, travel, declare_phase, resolve_phase, query_info],
    )
    call = game_tools(session, agent=agent)

    async def as_player(index, name, **arguments):
        with session._bind_authenticated_actor(world.ids[index], 1, lifecycle.require_authorized):
            return await call(name, **arguments)

    try:
        yield as_player, agent
    finally:
        await lifecycle.aclose()


async def place_party(world, location):
    session = world.ctx.userdata
    session.location_id = location
    for player_id in world.ids:
        await db_mutations.update_player_location(player_id, location, conn=world.pool)


async def prepare_discovery(world):
    await place_party(world, "greyvale_ruins_entrance")
    await db_mutations.set_player_quest(world.ids[0], "greyvale_anomaly", {"current_stage": 3}, conn=world.pool)


@pytest.fixture
async def travel_quest(world):
    quest_id = "fate_route_" + uuid4().hex
    data = {
        "name": "Follow the Trail",
        "stages": [
            {
                "id": "go",
                "completion_conditions": {"type": "location_reached", "location": DESTINATION},
                "on_complete": {"rewards": [{"item": "medicinal_herb", "quantity": 1}]},
            },
            {"id": "finish", "objective": "Inspect the ruins"},
        ],
        "scene_graph": [
            {"scene_id": "scene_millhaven_investigation", "stage_refs": [0]},
            {"scene_id": "scene_road_to_millhaven", "stage_refs": [1]},
        ],
    }
    await world.pool.execute("INSERT INTO quests (id,data) VALUES ($1,$2::jsonb)", quest_id, json.dumps(data))
    await db_mutations.set_player_quest(world.ids[0], quest_id, {"current_stage": 0}, conn=world.pool)
    try:
        yield quest_id
    finally:
        await world.pool.execute("DELETE FROM player_quests WHERE quest_id=$1", quest_id)
        await world.pool.execute("DELETE FROM quests WHERE id=$1", quest_id)


@asynccontextmanager
async def herb_node(world, location=DESTINATION):
    node_id = "fate_herb_" + uuid4().hex
    data = {
        "location_id": location,
        "node_type": "herb_garden",
        "resource_type": "plant_fiber",
        "quantity": 1,
        "discovered": False,
        "respawn_days": 0,
    }
    await world.pool.execute("INSERT INTO gathering_nodes (id,data) VALUES ($1,$2::jsonb)", node_id, json.dumps(data))
    try:
        yield node_id
    finally:
        await world.pool.execute("DELETE FROM gathering_nodes WHERE id=$1", node_id)


@pytest.fixture
async def argument_scene(world, party):
    del party
    host, guest = world.ids
    await configure(
        world,
        "veythar",
        "diplomat",
        index=1,
        location_id=ORIGIN,
        focus={"current": 3, "max": 20},
        attributes={"charisma": 16},
        conditions=INSPIRED,
    )
    enemies = [_enemy("pragmatist", 30), _enemy("skeptic", 30)]
    enemies[0].resistance_tags = ["pragmatic"]
    enemies[1].resistance_tags = ["suspicious"]
    state = _build_state(uuid4().hex, host, enemies)
    state.location_id = ORIGIN
    speaker = _player(guest)
    speaker.conditions = INSPIRED.copy()
    state.participants.append(speaker)
    state.initiative_order.insert(1, guest)
    place_actors(state)
    world.ctx.userdata.combat_state = state
    try:
        yield state
    finally:
        await db_mutations.delete_combat_state(state.combat_id)


def argument(actor, kind="reason"):
    return {"kind": "ability", "actor_id": actor, "action": "de_escalate", "targets": [], "argument_type": kind}


def declarations(state, *allies):
    return [*allies, *(defend(p.id) for p in state.participants if p.type == "enemy")]


async def quest_stage(player_id, quest_id):
    quest = await db_queries.get_player_quest(player_id, quest_id)
    assert quest is not None
    return quest["current_stage"]


async def quantity(player_id, item_id):
    inventory_item = await db_queries.get_inventory_item(player_id, item_id)
    return inventory_item["quantity"] if inventory_item is not None else 0
