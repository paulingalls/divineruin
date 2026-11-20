import json
from unittest.mock import patch

import pytest
from _zhael_fate_fixtures import attack, defend
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.test_architect_fight import fight as fight
from acceptance.test_architect_fight import isolated_content_cache as isolated_content_cache
from acceptance.test_architect_fight import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_architect_fight import pos

import check_resolution_save
import combat_spatial
import combat_structures
import db_queries


def move(actor_id, destination, *, movement_mode="ground", reshape=()):
    return {
        "kind": "move",
        "actor_id": actor_id,
        "destination": destination,
        "movement_mode": movement_mode,
        "reshape": list(reshape),
    }


async def declare(fight, *actions, error=False):
    return await fight.command("declare_phase", {"declarations": actions}, error=error)


async def play(fight, actor_id, *actions):
    await declare(fight, *actions)
    [packet] = [packet for packet in await fight.drain() if packet["actor_id"] == actor_id]
    return packet


async def set_favor(fight, patron, level):
    await fight.pool.execute(
        "UPDATE players SET data = jsonb_set(data, '{divine_favor}', $2::jsonb) WHERE player_id = $1",
        fight.players[0],
        json.dumps({"patron": patron, "level": level, "max": 100}),
    )


@pytest.mark.parametrize("succeeds,approach", [(True, False), (False, False), (False, True)])
async def test_floor_save_and_full_movement_exit(fight, succeeds, approach):
    state = await fight.reload()
    player = fight.players[0]
    owner = state.architect_encounter["owner_id"]
    start = pos(25)
    combat_spatial.place(state, player, start)
    state.spatial["speeds"][player] = 30
    state.get_participant(player).attributes["dexterity"] = 10
    state = await fight.persist()
    old_conditions = state.get_participant(player).conditions.copy()
    floor = {"kind": "open_floor", "min": pos(24, -5), "max": pos(29, 5)}
    with (
        patch("check_resolution.dice_roll", return_value=_d20(20 if succeeds else 1)),
        patch("architect_reshape.dice.roll", return_value=_damage_die(8)) as damage,
        patch(
            "architect_reshape.check_resolution_save.roll_participant_save",
            wraps=check_resolution_save.roll_participant_save,
        ) as save,
    ):
        summary = await play(fight, owner, defend(player), {**defend(owner), "reshape": [floor]})
    assert save.call_args.args[1:3] == ("DEX", 15)
    [receipt] = summary["reshape"]
    [result] = receipt["results"]
    assert receipt["targets"] == [player]
    assert result["save_success"] is succeeds
    state = await fight.reload()
    assert state.spatial["positions"][player] == start
    assert state.get_participant(owner).hp_current == state.get_participant(owner).hp_max
    hp = 100 if succeeds else 92
    row = await db_queries.get_player(player)
    assert row is not None and state.get_participant(player).hp_current == row["hp"]["current"] == hp
    if succeeds:
        damage.assert_not_called()
        assert state.get_participant(player).conditions == old_conditions
        assert not state.architect_encounter["pits"]
        return
    damage.assert_called_once_with("2d6")
    assert result["damage_type"] == "bludgeoning"
    assert state.architect_encounter["pits"] == {player: receipt["section_id"]}
    assert any(condition["type"] == "prone" for condition in state.get_participant(player).conditions)

    action = attack(player, owner) if approach else move(player, pos(20))
    result = await play(fight, player, action, defend(owner))
    assert result["left_pit"] and result["moved_ft"] == 0 and result["movement_spent_ft"] == 30
    if approach:
        assert not result["attack_resolved"]
    state = await fight.reload()
    assert not state.architect_encounter["pits"]
    assert any(condition["type"] == "prone" for condition in state.get_participant(player).conditions)
    stand = {"kind": "maneuver", "actor_id": player, "target_id": player}
    await play(fight, player, stand, defend(owner))
    result = await play(fight, player, move(player, pos(20)), defend(owner))
    assert result["moved_ft"] == 5 and result["movement_spent_ft"] == 10


async def test_low_ceilings_use_the_union_and_block_flight(fight):
    state = await fight.reload()
    player = fight.players[0]
    owner = state.architect_encounter["owner_id"]
    domain = next(iter(state.spatial["movement_areas"].values()))
    edge = domain["center"]["x"] + domain["radius_ft"]
    base = edge + 20
    combat_spatial.place(state, owner, pos(base, 20))
    combat_spatial.place(state, player, pos(base))
    architect = state.get_participant(owner)
    assert architect is not None
    architect.hp_current = (architect.hp_max - 1) // 2
    state.spatial["speeds"][player] = 30
    await fight.persist()
    ceiling = {"kind": "lower_ceiling", "min": pos(base + 5, -5, 25), "max": pos(base + 15, 5, 25)}
    overlap = {"kind": "lower_ceiling", "min": pos(base + 6, -4), "max": pos(base + 14, 4)}
    lowered = await play(fight, owner, {**defend(owner), "reshape": [ceiling, overlap]}, defend(player))
    assert len({receipt["section_id"] for receipt in lowered["reshape"]}) == 2

    failure = await declare(fight, move(player, pos(base + 20), movement_mode="flying"), error=True)
    assert "cannot fly through a lowered ceiling" in failure
    failure = await declare(fight, move(player, pos(base + 21)), error=True)
    assert "exceeds speed" in failure
    summary = await play(fight, player, move(player, pos(base + 20)))
    assert (summary["moved_ft"], summary["movement_spent_ft"]) == (20, 30)
    summary = await play(fight, player, move(player, pos(base + 20, 10, 25), movement_mode="flying"))
    assert summary["resolved"]
    state = await fight.reload()
    combat_spatial.place(state, player, pos(base, 0, 40))
    await fight.persist()
    summary = await play(fight, player, move(player, pos(base + 10, 10, 40), movement_mode="flying"))
    assert summary["movement_spent_ft"] == pytest.approx(200**0.5)
    state = await fight.reload()
    combat_spatial.place(state, owner, pos(base))
    await fight.persist()
    summary = await play(fight, owner, move(owner, pos(base + 20)))
    assert summary["movement_spent_ft"] == 30


@pytest.mark.parametrize("case", ["enter", "leave", "inside", "outside", "tangent", "through", "overlap"])
async def test_domain_expenditure_and_boundary(fight, case):
    state = await fight.reload()
    player = fight.players[0]
    owner = state.architect_encounter["owner_id"]
    facts = await fight.command("query_info", {"kind": "combat"})
    [domain] = [area for area in facts["movement_areas"].values() if area["kind"] == "architect_domain"]
    center, radius = domain["center"], domain["radius_ft"]
    x, y, z = (center[axis] for axis in ("x", "y", "z"))
    edge = x + radius
    a, b, cost = {
        "enter": (pos(edge + 10, y, z), pos(edge - 10, y, z), 30),
        "leave": (pos(edge - 10, y, z), pos(edge + 10, y, z), 30),
        "inside": (pos(edge - 30, y, z), pos(edge - 10, y, z), 40),
        "outside": (pos(edge + 10, y, z), pos(edge + 30, y, z), 20),
        "tangent": (pos(edge, y - 10, z), pos(edge, y + 10, z), 20),
        "through": (pos(x - radius - 10, y, z), pos(edge + 10, y, z), 4 * radius + 20),
        "overlap": (pos(edge - 10, y, z), pos(edge + 10, y, z), 35),
    }[case]
    if case == "overlap":
        combat_spatial.place(state, owner, pos(edge, y + 20, z))
        await fight.persist()
        ceiling = {"kind": "lower_ceiling", "min": pos(edge - 5, y - 5, z), "max": pos(edge + 5, y + 5, z)}
        await play(fight, owner, {**defend(owner), "reshape": [ceiling]})
        state = await fight.reload()
    combat_spatial.place(state, player, a)
    state.spatial["speeds"][player] = cost - 1
    await fight.persist()
    failure = await declare(fight, move(player, b), error=True)
    assert "exceeds speed" in failure
    state = await fight.reload()
    state.spatial["speeds"][player] = cost
    await fight.persist()
    result = await play(fight, player, move(player, b))
    assert result["movement_spent_ft"] == pytest.approx(cost)


async def test_partial_melee_approach_uses_domain_allowance(fight):
    state = await fight.reload()
    player = fight.players[0]
    owner = state.architect_encounter["owner_id"]
    combat_spatial.place(state, owner, pos(30))
    combat_spatial.place(state, player, pos(0))
    state.spatial["speeds"][player] = 30
    await fight.persist()
    packet = await play(fight, player, attack(player, owner), defend(owner))
    assert not packet["attack_resolved"]
    assert (packet["moved_ft"], packet["movement_spent_ft"], packet["destination"]) == (15, 30, pos(15))


async def test_owned_and_condition_bypasses_apply_only_to_movement(fight):
    state = await fight.reload()
    player = fight.players[0]
    owner = state.architect_encounter["owner_id"]
    combat_spatial.place(state, owner, pos(5, 1))
    combat_spatial.place(state, player, pos(5, 3))
    await fight.persist()
    wall = {"kind": "create_wall", "start": pos(0, 10), "end": pos(10, 10)}
    result = await play(fight, owner, move(owner, pos(5, 14), reshape=[wall]))
    assert result["moved_ft"] == result["movement_spent_ft"] == 13
    [created] = result["reshape"]
    state = await fight.reload()
    combat_structures.add_wall(state, "foreign", "Foreign wall", pos(0, 17), pos(10, 17))
    await fight.persist()
    assert "foreign" in await declare(fight, move(owner, pos(5, 20)), error=True)
    assert created["section_id"] in await declare(fight, move(player, pos(5, 14)), error=True)
    assert created["section_id"] in await declare(
        fight, {**attack(owner, player), "action": "Geometry Strike"}, error=True
    )

    await set_favor(fight, "mortaen", 75)
    gifts = await fight.command("query_info", {"kind": "patron"})
    gift = next(gift for gift in gifts["abilities"] if gift["id"] == "mortaen_threshold_walk")
    await fight.command("activate", {"id": gift["id"]})
    state = await fight.reload()
    assert any(condition["type"] == "incorporeal" for condition in state.get_participant(player).conditions)
    before = await fight.snapshot()
    assert "Line blocked" in await declare(fight, attack(player, owner), error=True)
    spell = {"kind": "ability", "actor_id": player, "action": "arcane_bolt", "targets": [owner], "argument_type": ""}
    assert "Line blocked" in await declare(fight, spell, error=True)
    assert await fight.snapshot() == before
    packet = await play(fight, player, move(player, pos(5, 18)))
    assert packet["moved_ft"] == 15
    await play(fight, player, defend(player))
    state = await fight.reload()
    assert all(condition["type"] != "incorporeal" for condition in state.get_participant(player).conditions)
    assert "foreign" in await declare(fight, move(player, pos(5, 15)), error=True)
