"""Seed shaped encounters and drive the registered combat tools."""

import json
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.mawling_harness import MawlingHarness
from acceptance.seeds import seed_known_spells
from acceptance.test_architect_fight import pos
from acceptance.test_opportunity_strike import participant
from acceptance.test_slippery_restrain import strike
from acceptance.test_wild_shape import ABILITY, declare, enter, prepare
from acceptance.test_wild_shape import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_wild_shape_guards import follow_thyra
from livekit.agents.llm import FunctionTool

import combat_spatial
import db_queries
from activate_tools import activate
from combat_turn import resolve_phase


@pytest.fixture
async def fight(reset_db_pool: str, request: pytest.FixtureRequest) -> AsyncIterator[MawlingHarness]:
    harness = MawlingHarness()
    options = getattr(request, "param", "phase")
    route, _, scenario = options.partition(":")
    try:
        await harness.prepare((5, 6), companion=None, tools=(activate,))
        harness.encounter_id = "bandit_ambush"
        level = 10 if scenario == "bear" else 5
        pid = await prepare(harness, "druid", level, focus=10)
        guest = harness.players[1]
        if scenario == "intercept":
            await patch_player(harness, guest, **{"class": "guardian"})
        if scenario == "spell":
            await patch_player(harness, guest, **{"class": "mage", "focus": {"current": 30, "max": 30}})
            await seed_known_spells(harness.pool, guest, ("arcane_fireball",))
        if scenario in ("mawling", "drain"):
            creature_id = "hollow_mawling" if scenario == "mawling" else "hollow_warden"
            await replace_bandit(harness, creature_id)
        if route == "phase" and scenario in ("bear", "intercept"):
            await patch_player(harness, pid, divine_favor={"patron": "zhael", "level": 0, "max": 100})
        if scenario == "inner_fire":
            await patch_player(harness, pid, race="draethar")
        if scenario == "verdict":
            await patch_player(harness, pid, divine_favor={"patron": "valdris", "level": 90, "max": 100})
        await harness.pool.execute(
            "UPDATE players SET data=jsonb_set(data,'{hp}','{\"current\":30,\"max\":30}') WHERE player_id=$1", pid
        )
        if scenario == "thyra":
            await follow_thyra(harness, pid)
        await enter(harness)
        if route == "immediate":
            agent = harness.session.current_agent
            await agent.update_tools(
                [
                    resolve_phase if isinstance(tool, FunctionTool) and tool.id == "resolve_phase" else tool
                    for tool in agent.tools
                ]
            )
        await declare(harness, ABILITY, "dire_bear" if scenario == "bear" else "grey_wolf")
        await harness.drain()
        state = await harness.reload()
        participant(state, "bandit_1").damage_mult = 1.0
        positions = combat_spatial.require_spatial(state)["positions"]
        if scenario in ("mawling", "drain"):
            positions.update({pid: pos(0), "bandit_1": pos(5)})
        if scenario == "intercept":
            positions.update({pid: pos(0), guest: pos(5)})
        if scenario == "spell":
            positions.update({pid: pos(40), guest: pos(0)})
        await harness.persist()
        yield harness
    finally:
        await harness.close()


async def patch_player(fight: MawlingHarness, pid: str, **fields) -> None:
    await fight.pool.execute("UPDATE players SET data=data || $2::jsonb WHERE player_id=$1", pid, json.dumps(fields))


async def replace_bandit(fight: MawlingHarness, creature_id: str) -> None:
    template = json.loads(
        await fight.pool.fetchval("SELECT data FROM encounter_templates WHERE id=$1", fight.encounter_id)
    )
    fight.encounter_id = f"shape_hp_{uuid4().hex}"
    fight.owns_template = True
    template["id"] = fight.encounter_id
    bandit = next(enemy for enemy in template["enemies"] if enemy["id"] == "bandit_1")
    bandit.update(creature_id=creature_id, role="standard")
    await fight.pool.execute(
        "INSERT INTO encounter_templates (id,data) VALUES ($1,$2::jsonb)", fight.encounter_id, json.dumps(template)
    )


async def declare_round(fight: MawlingHarness, *actions: dict) -> None:
    state = await fight.reload()
    actors = {action["actor_id"] for action in actions}
    await fight.command(
        "declare_phase",
        {
            "declarations": [
                *actions,
                *(
                    {"kind": "defend", "actor_id": p.id, "reshape": []}
                    for p in state.participants
                    if p.id not in actors
                ),
            ],
        },
    )


async def declare_hit(fight: MawlingHarness, action: str = "Light Crossbow") -> None:
    await declare_round(fight, strike("bandit_1", fight.players[0], action))


def damage_roll(monkeypatch: pytest.MonkeyPatch, amount: int, face: int = 17) -> None:
    monkeypatch.setattr("check_resolution.dice_roll", lambda *_, **__: _d20(face))
    monkeypatch.setattr("check_resolution_attack.dice_roll", lambda *_, **__: _damage_die(amount))


async def land(fight: MawlingHarness, monkeypatch: pytest.MonkeyPatch, amount: int) -> dict:
    await declare_hit(fight)
    damage_roll(monkeypatch, amount)
    return next(packet for packet in await fight.drain() if packet["actor_id"] == "bandit_1")


async def saved_pools(fight: MawlingHarness) -> tuple[int, int, int | None]:
    pid = fight.players[0]
    actor = participant(await fight.reload(), pid)
    row = await db_queries.get_player(pid)
    assert row is not None
    assert actor.hp_current == row["hp"]["current"]
    assert actor.temp_hp == row.get("temp_hp", 0)
    return actor.hp_current, actor.temp_hp, actor.wild_shape["hp_current"] if actor.wild_shape else None


async def set_temp(fight: MawlingHarness, pid: str, amount: int) -> None:
    participant(await fight.reload(), pid).temp_hp = amount
    await patch_player(fight, pid, temp_hp=amount)
    await fight.persist()


def events(fight: MawlingHarness) -> list[dict]:
    assert fight.sd.room is not None
    publish = fight.sd.room.local_participant.publish_data
    assert isinstance(publish, AsyncMock)
    return [json.loads(call.args[0]) for call in publish.call_args_list]
