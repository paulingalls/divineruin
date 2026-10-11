"""Fallen damage through roomless commands and committed combat placement."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_mawling_multiattack import catalog

from combat_phase import is_terminally_down
from creature_combat import _action


@pytest.fixture
def mock_combat_agent_factory():
    return None


@pytest.fixture
async def maw(reset_db_pool, request):
    harness = MawlingHarness()
    try:
        await harness.start(**getattr(request, "param", {}))
        yield harness
    finally:
        await harness.close()


@pytest.fixture
def dice():
    with (
        patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=15)) as d20,
        patch("check_resolution_attack.dice_roll", return_value=SimpleNamespace(total=4)),
        patch("combat_enemy_action.dice_roll", return_value=SimpleNamespace(total=4)),
    ):
        yield d20


async def fallen(maw, target, failures=0, distance=5, actor=None):
    state = maw.sd.combat_state
    victim = state.get_participant(target)
    victim.hp_current = 0
    victim.is_fallen = True
    victim.death_save_failures = failures
    victim.death_save_successes = 0
    state.spatial["positions"][target] = {"x": 0, "y": 0, "z": 0}
    state.spatial["positions"][actor or maw.enemies[0]] = {"x": distance, "y": 0, "z": 0}
    await maw.persist()


async def strike(maw, target, action="Claw", actor=None):
    actor = actor or maw.enemies[0]
    state = maw.sd.combat_state
    await maw.command(
        "declare_phase",
        {
            "declarations": [
                {
                    "kind": "attack",
                    "actor_id": actor,
                    "action": action,
                    "target_id": target,
                    "held_item_id": "",
                    "rider": "",
                },
                *[
                    {"kind": "defend", "actor_id": p.id}
                    for p in state.participants
                    if p.id != actor and not p.is_fallen
                ],
            ]
        },
    )
    packets = await maw.drain()
    packet = next(p for p in packets if p.get("actor_id") == actor)
    assert packet["resolved"], packet
    return packet


@pytest.mark.parametrize("distance,initial,expected", [(5, 0, 2), (5, 2, 3), (5.01, 0, 1), (10, 0, 1)])
async def test_claw_distance_and_player_death(maw, dice, distance, initial, expected):
    await fallen(maw, maw.players[0], initial, distance)
    packet = await strike(maw, maw.players[0])
    assert packet["hit"] and packet["damage"] > 0
    victim = (await maw.reload()).get_participant(maw.players[0])
    assert victim.death_save_failures == expected
    assert is_terminally_down(victim) == (expected == 3)


@pytest.mark.parametrize("mode", ["boolean", "property", "area", "save", "miss"])
async def test_other_damage_and_miss(maw, dice, mode):
    await fallen(maw, maw.players[0])
    actor = maw.sd.combat_state.get_participant(maw.enemies[0])
    action = copy.deepcopy(next(a for a in actor.action_pool if a["name"] == "Claw"))
    if mode in ("boolean", "property"):
        action.pop("type", None)
        if mode == "boolean":
            action["ranged"] = True
        else:
            action["properties"] = ["ranged"]
    elif mode == "area":
        row = next(r for r in catalog() if r["id"] == "deepstone_guardian")
        action = _action(next(a for a in row["actions"] if a["name"] == "Guardian Pulse"))
    elif mode == "save":
        shapes = json.loads(
            (Path(__file__).parents[4] / "packages/shared/fixtures/enemy_action_shapes.json").read_text()
        )
        action = shapes["valid_half_on_success"]
        dice.return_value = SimpleNamespace(total=1)
    else:
        dice.return_value = SimpleNamespace(total=1)
    actor.action_pool = [action]
    await maw.persist()
    packet = await strike(maw, maw.players[0], action["name"])
    if mode == "save":
        assert "hit" not in packet and packet["damage"] > 0
    else:
        assert packet["hit"] == (mode != "miss")
        assert (packet["damage"] > 0) == (mode != "miss")
    victim = (await maw.reload()).get_participant(maw.players[0])
    assert victim.death_save_failures == (0 if mode == "miss" else 1)


@pytest.mark.parametrize("maw", [{"companion": True}], indirect=True)
@pytest.mark.parametrize("initial", [0, 1])
async def test_companion_impact_and_wrap(maw, dice, initial):
    target = maw.sd.companion.id
    await fallen(maw, target, initial)
    packet = await strike(maw, target)
    assert packet["hit"] and packet["damage"] > 0
    assert packet["death_save_failures"] == initial + 2
    victim = (await maw.reload()).get_participant(target)
    assert victim.death_save_failures == 2 and not victim.is_dead
    if initial:
        assert victim.death_save_successes == 3
        assert target not in maw.last_result["death_saves_due"]


@pytest.mark.parametrize("maw", [{"gear": True}], indirect=True)
async def test_equipment_melee_from_real_hollowed_echo(maw, dice):
    victim = maw.sd.combat_state.get_participant(maw.players[1])
    victim.hp_current = 1
    victim.conditions.append({"type": "hollowed", "stage": 2, "duration": None})
    await maw.persist()
    packet = await strike(maw, victim.id)
    assert packet["target_rose_hollowed"]
    echo = (await maw.reload()).get_participant(victim.id)
    assert echo.type == "temporary_hollowed"
    action = echo.action_pool[0]
    assert "type" not in action and "attack_source" not in action
    await fallen(maw, maw.players[0], actor=echo.id)
    packet = await strike(maw, maw.players[0], action["name"], echo.id)
    assert packet["hit"] and packet["damage"] > 0
    assert (await maw.reload()).get_participant(maw.players[0]).death_save_failures == 2
