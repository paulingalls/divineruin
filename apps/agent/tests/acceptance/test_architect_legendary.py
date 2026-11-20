from copy import deepcopy
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.test_architect_fight import fight as fight
from acceptance.test_architect_fight import isolated_content_cache as isolated_content_cache
from acceptance.test_architect_fight import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_architect_fight import pos
from acceptance.test_architect_reshape import declare

import combat_spatial
import db_mutations
import db_queries


async def test_first_round_legendary_options(fight):
    state = await fight.reload()
    owner_id = state.architect_encounter["owner_id"]
    owner = state.get_participant(owner_id)
    assert (owner.role, state.round_number, owner.legendary_actions) == ("named", 1, 3)
    facts = (await fight.command("query_info", {"kind": "combat", "target_id": owner_id}))["architect"]
    assert {a["id"]: a["cost"] for a in facts["legendary"]["actions"]} == {
        "Geometry Strike": 2,
        "Shift Wall": 1,
        "Reshape": 2,
    }


async def spend(fight, owner, action, *, target="", operations=(), error=False):
    return await fight.command(
        "consume_legendary_action",
        {"boss_id": owner, "action_id": action, "target_id": target, "reshape": list(operations)},
        error=error,
    )


async def test_legendary_spends_preserve_enemy_queue(fight):
    state = await fight.reload()
    owner = state.architect_encounter["owner_id"]
    player = fight.players[0]
    wall = state.architect_encounter["structure_ids"][0]
    state.get_participant(player).reaction_ids = []
    combat_spatial.place(state, player, pos(15, 4))
    state.get_participant(wall).hp_current = 17
    await fight.persist()
    await declare(fight, {"kind": "defend", "actor_id": owner, "reshape": []})
    await fight.command("resolve_phase", {})
    state = await fight.reload()
    tail = deepcopy(state.held_actions)
    old_hp = state.get_participant(player).hp_current
    old_wall = deepcopy(state.spatial["structures"][wall])
    old_center = deepcopy(state.spatial["positions"][wall])
    other_walls = {key: value for key, value in state.spatial["structures"].items() if key != wall}
    wall_ac = state.get_participant(wall).ac

    with (
        patch("check_resolution.dice_roll", return_value=_d20(15)) as roll,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        strike = await spend(fight, owner, "Geometry Strike", target=player)
    roll.assert_called_once()
    [packet] = strike["packets"]
    assert packet["damage"] == 4 and strike["legendary_actions_remaining"] == 1
    state = await fight.reload()
    assert state.get_participant(player).hp_current == old_hp - 4
    row = await db_queries.get_player(player)
    assert row is not None and row["hp"]["current"] == old_hp - 4

    moved = {k: {**v, "y": v["y"] + 30} for k, v in old_wall.items()}
    shift = {"kind": "move_wall", "wall_id": wall, **moved}
    shifted = await spend(fight, owner, "Shift Wall", operations=[shift])
    assert shifted["legendary_actions_remaining"] == 0
    state = await fight.reload()
    structure = state.get_participant(wall)
    assert (structure.hp_current, structure.ac) == (17, wall_ac)
    assert state.spatial["positions"][wall] == {**old_center, "y": old_center["y"] + 30}
    assert state.spatial["structures"] == {**other_walls, wall: moved}
    assert state.round_number == 1 and state.held_actions == tail
    assert "remaining" in await spend(fight, owner, "Shift Wall", operations=[shift], error=True)
    assert (await fight.reload()).to_dict() == state.to_dict()
    await fight.drain()
    state = await fight.reload()
    assert state.round_number == 2 and state.get_participant(owner).legendary_actions == 3
    moved_again = {"kind": "move_wall", "wall_id": wall, **old_wall}
    assert (await spend(fight, owner, "Shift Wall", operations=[moved_again]))["legendary_actions_remaining"] == 2


async def test_legendary_reshape_ignores_used_free_allowance(fight):
    state = await fight.reload()
    owner = state.architect_encounter["owner_id"]
    state.architect_encounter.update(reshape_round=1, reshape_count=1)
    await fight.persist()
    wall = state.architect_encounter["structure_ids"][0]
    result = await spend(fight, owner, "Reshape", operations=[{"kind": "destroy_wall", "wall_id": wall}])
    assert result["legendary_actions_remaining"] == 1
    assert result["packets"][0]["reshape"] == [{"kind": "destroy_wall", "section_id": wall}]
    state = await fight.reload()
    assert state.get_participant(wall).is_dead
    assert state.architect_encounter["reshape_count"] == 1


@pytest.mark.parametrize("kind", ["create_wall", "move_wall", "destroy_wall", "open_floor", "lower_ceiling"])
async def test_legendary_reshape_has_the_same_section_effects_as_free_reshape(fight, kind):
    state = await fight.reload()
    owner = state.architect_encounter["owner_id"]
    player = fight.players[0]
    wall = state.architect_encounter["structure_ids"][0]
    combat_spatial.place(state, player, pos(5))
    state.get_participant(player).attributes["dexterity"] = 10
    start = deepcopy(await fight.persist())
    operations = {
        "create_wall": {"start": pos(25), "end": pos(25, 10)},
        "move_wall": {"wall_id": wall, "start": pos(25), "end": pos(25, 10)},
        "destroy_wall": {"wall_id": wall},
        "open_floor": {"min": pos(4, -5), "max": pos(6, 5)},
        "lower_ceiling": {"min": pos(4, -5), "max": pos(6, 5)},
    }
    operation = {"kind": kind, **operations[kind]}
    with (
        patch("check_resolution.dice_roll", return_value=_d20(1)),
        patch("architect_reshape.dice.roll", return_value=_damage_die(8)),
    ):
        legendary = await spend(fight, owner, "Reshape", operations=[operation])
        legendary_state = await fight.reload()
        fight.sd.combat_state = start
        await fight.persist()
        await declare(fight, {"kind": "defend", "actor_id": owner, "reshape": [operation]})
        [free] = [packet for packet in await fight.drain() if packet["actor_id"] == owner]
        free_state = await fight.reload()
    assert legendary["legendary_actions_remaining"] == 1
    assert legendary["packets"][0]["reshape"] == free["reshape"]
    assert legendary_state.spatial == free_state.spatial
    for field in ("structure_ids", "floors", "pits"):
        assert legendary_state.architect_encounter[field] == free_state.architect_encounter[field]
    for field in ("hp_current", "conditions"):
        assert getattr(legendary_state.get_participant(player), field) == getattr(
            free_state.get_participant(player), field
        )
    if kind == "open_floor":
        [victim] = free["reshape"][0]["results"]
        assert victim["damage"] == 8 and victim["prone"]


async def test_lethal_legendary_strike_hands_off_once_on_ordinary_resolve(fight):
    state = await fight.reload()
    owner = state.architect_encounter["owner_id"]
    player = fight.players[0]
    target = state.get_participant(player)
    target.hp_current = 1
    target.reaction_ids = []
    combat_spatial.place(state, player, pos(15, 5))
    await fight.persist()
    await declare(fight, {"kind": "defend", "actor_id": owner, "reshape": []})
    await fight.command("resolve_phase", {})
    with patch("dice.roll", return_value=_damage_die(102)):
        result = await spend(fight, owner, "Geometry Strike", target=player)
    assert result["packets"][0]["damage"] == 102
    state = await fight.reload()
    assert state.get_participant(player).is_dead
    assert state.round_number == 1
    result = await fight.command("resolve_phase", {})
    assert result["outcome"] == "defeat"
    assert fight.sd.combat_state is None
    assert await db_mutations.load_combat_state(state.combat_id) is None
