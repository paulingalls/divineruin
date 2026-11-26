from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.test_architect_fight import fight as fight
from acceptance.test_architect_fight import isolated_content_cache as isolated_content_cache
from acceptance.test_architect_fight import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_architect_fight import pos

import combat_attack_roll
import combat_spatial
import combat_structures
from declarations import DEFEND_AC_BONUS


async def declare(fight, owner_action, *, error=False):
    return await fight.command(
        "declare_phase",
        {
            "declarations": [{"kind": "defend", "actor_id": player, "reshape": []} for player in fight.players]
            + [owner_action]
        },
        error=error,
    )


async def test_wall_reshapes_in_resolution(fight):
    state = await fight.reload()
    owner = state.architect_encounter["owner_id"]
    wall = state.architect_encounter["structure_ids"][0]
    await declare(
        fight,
        {"kind": "defend", "actor_id": owner, "reshape": [{"kind": "destroy_wall", "wall_id": wall}]},
    )
    assert wall in (await fight.reload()).spatial["structures"]
    await fight.drain()
    state = await fight.reload()
    assert state.get_participant(wall).is_dead
    assert wall not in state.spatial["structures"]


async def test_wall_moves_keep_damage_and_change_attack_preparation(fight):
    state = await fight.reload()
    owner = state.architect_encounter["owner_id"]
    player = fight.players[0]
    combat_spatial.place(state, owner, pos(0))
    combat_spatial.place(state, player, pos(20, 11))
    facts = (await fight.command("query_info", {"kind": "combat", "target_id": owner}))["architect"]
    wall = facts["live_wall_ids"][0]
    state.get_participant(wall).hp_current = 17
    await fight.persist()

    strike = {
        "quick_fingers_mode": "",
        "quick_fingers_item": "",
        "kind": "attack",
        "actor_id": owner,
        "target_id": player,
        "action": "Geometry Strike",
        "held_item_id": "",
        "rider": "",
    }
    blocked = await declare(fight, {**strike, "reshape": []}, error=True)
    assert wall in blocked
    movement = {"kind": "move_wall", "wall_id": wall, "start": pos(20, 15), "end": pos(38, 15)}
    await declare(fight, {**strike, "reshape": [movement]})
    with (
        patch("check_resolution.dice_roll", side_effect=AssertionError("automatic hit prepared a d20")),
        patch("dice.roll", return_value=_damage_die(12)),
    ):
        [packet] = [p for p in await fight.drain() if p["actor_id"] == owner]
    assert packet["hit"] and packet["damage"] > 0
    assert packet["reshape"] == [{"kind": "move_wall", "section_id": wall}]
    state = await fight.reload()
    assert state.get_participant(wall).hp_current == 17
    assert state.spatial["structures"][wall] == {"start": pos(20, 15), "end": pos(38, 15)}

    before = state.to_dict()
    create = {"kind": "create_wall", "start": pos(0, 5), "end": pos(20, 5)}
    refused = await declare(fight, {**strike, "reshape": [create]}, error=True)
    assert "Line blocked" in refused
    assert (await fight.reload()).to_dict() == before

    await declare(fight, {**strike, "reshape": [{"kind": "destroy_wall", "wall_id": wall}]})
    with patch("check_resolution.dice_roll", return_value=_d20(1)) as rolls:
        [packet] = [p for p in await fight.drain() if p["actor_id"] == owner]
    assert not packet["hit"]
    rolls.assert_called_once()


async def test_round_budget_is_strictly_below_half(fight):
    state = await fight.reload()
    owner = state.architect_encounter["owner_id"]
    actor = state.get_participant(owner)
    origin = state.spatial["positions"][owner]
    first = {
        "kind": "create_wall",
        "start": {**origin, "x": origin["x"] + 100},
        "end": {**origin, "x": origin["x"] + 120},
    }
    second = {
        "kind": "lower_ceiling",
        "min": {**origin, "x": origin["x"] + 25},
        "max": {**origin, "x": origin["x"] + 45, "y": origin["y"] + 20},
    }
    action = {"kind": "defend", "actor_id": owner}
    actor.hp_current = (actor.hp_max + 1) // 2  # the lowest HP that is not below half
    state = await fight.persist()
    response = await declare(fight, {**action, "reshape": [first, second]}, error=True)
    assert "budget" in response
    assert (await fight.reload()).to_dict() == state.to_dict()

    await declare(fight, {**action, "reshape": [first]})
    await fight.drain()
    state = await fight.reload()
    assert state.architect_encounter["reshape_count"] == 1
    assert state.architect_encounter["reshape_round"] == state.round_number - 1

    actor = state.get_participant(owner)
    actor.hp_current -= 1
    state = await fight.persist()
    response = await declare(fight, {**action, "reshape": [first, second, first]}, error=True)
    assert "budget" in response and "2 use" in response
    assert (await fight.reload()).to_dict() == state.to_dict()

    await declare(fight, {**action, "reshape": [first, second]})
    [packet] = [p for p in await fight.drain() if p["actor_id"] == owner]
    assert [receipt["kind"] for receipt in packet["reshape"]] == ["create_wall", "lower_ceiling"]
    assert (await fight.reload()).architect_encounter["reshape_count"] == 2


@pytest.mark.parametrize(
    "operation,reason",
    [
        ({"kind": "create_wall", "start": pos(100), "end": pos(120.01)}, "120-foot"),
        ({"kind": "create_wall", "start": pos(0), "end": pos(15, 14)}, "20-foot"),
        ({"kind": "open_floor", "min": pos(99), "max": pos(119, 20)}, "120-foot"),
        ({"kind": "open_floor", "min": pos(-1), "max": pos(20, 1)}, "20-foot"),
        ({"kind": "lower_ceiling", "min": pos(0, 0), "max": pos(1, 20.01)}, "20-foot"),
        ({"kind": "destroy_wall", "wall_id": "foreign"}, "live wall owned"),
    ],
)
async def test_refusal_changes_no_geometry(fight, operation, reason):
    state = await fight.reload()
    owner = state.architect_encounter["owner_id"]
    combat_spatial.place(state, owner, pos(0))
    combat_structures.add_wall(state, "foreign", "Foreign wall", pos(30, -1), pos(30, 1))
    state = await fight.persist()
    response = await declare(fight, {"kind": "defend", "actor_id": owner, "reshape": [operation]}, error=True)
    assert reason in response
    assert (await fight.reload()).to_dict() == state.to_dict()


async def test_player_cannot_reshape(fight):
    state = await fight.reload()
    player = fight.players[0]
    failure = await fight.command(
        "declare_phase",
        {
            "declarations": [
                {
                    "kind": "defend",
                    "actor_id": player,
                    "reshape": [{"kind": "open_floor", "min": pos(0), "max": pos(1, 1)}],
                }
            ]
        },
        error=True,
    )
    assert "Only the Architect" in failure
    assert (await fight.reload()).to_dict() == state.to_dict()


async def test_architect_incapacitated_after_declaration_spends_nothing(fight):
    from conditions import apply_condition

    state = await fight.reload()
    owner = state.architect_encounter["owner_id"]
    [wall, *_] = state.architect_encounter["structure_ids"]
    await declare(
        fight,
        {"kind": "defend", "actor_id": owner, "reshape": [{"kind": "destroy_wall", "wall_id": wall}]},
    )
    state = await fight.reload()
    actor = state.get_participant(owner)
    actor.conditions = apply_condition(actor.conditions, "stunned", source=fight.players[0], duration=1)
    await fight.persist()
    [result] = [packet for packet in await fight.drain() if packet["actor_id"] == owner]
    assert result["resolved"] is False and "unavailable" in result["reason"]
    state = await fight.reload()
    assert state.architect_encounter["reshape_count"] == 0
    assert wall in state.spatial["structures"]


async def test_defend_with_reshape_guards_against_earlier_attackers(fight):
    state = await fight.reload()
    record = state.architect_encounter
    owner, player, south = record["owner_id"], fight.players[0], record["structure_ids"][1]
    combat_spatial.place(state, player, pos(13, 9))
    state.initiative_order = [player, *(p for p in state.initiative_order if p != player)]
    await fight.persist()
    strike = {
        "quick_fingers_mode": "",
        "quick_fingers_item": "",
        "kind": "attack",
        "actor_id": player,
        "target_id": owner,
        "action": "Longsword",
    }
    reshape = [{"kind": "destroy_wall", "wall_id": south}]
    await fight.command(
        "declare_phase",
        {
            "declarations": [
                {**strike, "held_item_id": "", "rider": "", "reshape": []},
                {"kind": "defend", "actor_id": owner, "reshape": reshape},
                *[{"kind": "defend", "actor_id": p, "reshape": []} for p in fight.players if p != player],
            ]
        },
    )
    with patch("combat_attack_roll.attack_roll_inputs", wraps=combat_attack_roll.attack_roll_inputs) as inputs:
        await fight.drain()
    [bonus] = [c.args[2] for c in inputs.call_args_list if c.args[1].id == owner]
    assert bonus == DEFEND_AC_BONUS
    assert (await fight.reload()).get_participant(south).is_dead
