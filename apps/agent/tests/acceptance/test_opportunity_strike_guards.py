from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_entomb import favor
from acceptance.test_architect_fight import pos
from acceptance.test_opportunity_strike import (
    MOVER,
    STRIKE,
    activate_as,
    advance_to_departure,
    declare_attack,
    participant,
    reconnect,
)
from acceptance.test_opportunity_strike import fight as fight
from acceptance.test_opportunity_strike import mock_combat_agent_factory as mock_combat_agent_factory

from combat_spatial import require_spatial
from combat_structures import add_wall


@pytest.mark.parametrize(
    "fight,ceiling,reacts",
    [("steppe_razorwing", False, False), ("steppe_razorwing", True, True), ("hollow_hollowmoth", False, True)],
    indirect=["fight"],
)
async def test_flyby_depends_on_effective_mode(fight: MawlingHarness, ceiling: bool, reacts: bool) -> None:
    warrior, target = fight.players
    state = await fight.reload()
    require_spatial(state)["positions"][target] = pos(13)
    if ceiling:
        require_spatial(state)["movement_areas"] = {
            "ceiling": {
                "shape": "rectangle",
                "kind": "low_ceiling",
                "min": pos(2, -1),
                "max": pos(10, 1),
                "excluded_actor_ids": [],
            }
        }
    await fight.persist()
    with (
        patch("check_resolution.dice_roll", return_value=_d20(18)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(1)),
    ):
        result = await advance_to_departure(fight)
        waiting = result["next"]["waiting_on"]
        assert waiting and (waiting["stage"] == "movement") is reacts
        if reacts:
            assert require_spatial(await fight.reload())["positions"][MOVER] == pos(5)
            await activate_as(fight, warrior)
            result = await fight.command("resolve_phase", {})
            assert any(packet.get("reaction") == STRIKE for packet in result["packets"])
        packets = result["packets"]
        if result["next"]["phase"] != "declaration":
            packets += await fight.drain()
    attack = next(packet for packet in packets if packet["actor_id"] == MOVER and "hit" in packet)
    assert attack["movement_mode"] == ("ground" if ceiling else "flying")
    if ceiling:
        assert attack["movement_spent_ft"] == 10
    assert attack["hit"]


@pytest.mark.parametrize("origin,target_x", [(-8, 25), (3, 9)])
async def test_segment_must_start_inside_and_end_outside(fight: MawlingHarness, origin: int, target_x: int) -> None:
    state = await fight.reload()
    require_spatial(state)["positions"].update({MOVER: pos(origin), fight.players[1]: pos(target_x)})
    require_spatial(state)["speeds"][MOVER] = 40
    if origin < 0:
        # The long-reach off-hand can shortlist this warrior. The five-foot main hand sets the actual boundary.
        warrior = participant(state, fight.players[0])
        warrior.action_pool.append({"name": "Whip", "damage": "1d4", "properties": ["reach"]})
    await fight.persist()
    with (
        patch("check_resolution.dice_roll", return_value=_d20(18)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        result = await advance_to_departure(fight)
        assert result["next"]["waiting_on"]["stage"] == "post_roll"


async def test_diagonal_exit_at_weapon_reach(fight: MawlingHarness) -> None:
    state = await fight.reload()
    require_spatial(state)["positions"].update({MOVER: pos(1, 2, 2), fight.players[1]: pos(7, 14, 14)})
    await fight.persist()
    result = await advance_to_departure(fight)
    assert result["next"]["waiting_on"]["stage"] == "movement"
    paused = await fight.reload()
    assert require_spatial(paused)["positions"][MOVER] == pytest.approx(pos(5 / 3, 10 / 3, 10 / 3))


@pytest.mark.parametrize("fight", ["party"], indirect=True)
async def test_exits_in_path_order(fight: MawlingHarness) -> None:
    first, _, second = fight.players
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(15), _d20(1), _d20(18)]) as rolls,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        result = await advance_to_departure(fight)
        one = result["next"]["waiting_on"]
        assert one and one["window_id"].endswith("-movement-0")
        assert [entry["actor_id"] for entry in one["reactions"]] == [first]
        assert require_spatial(await fight.reload())["positions"][MOVER] == pos(5)
        assert "this exit" in await activate_as(fight, second, error=True)
        await activate_as(fight, first)
        result = await fight.command("resolve_phase", {})
        two = result["next"]["waiting_on"]
        assert two and two["window_id"].endswith("-movement-1")
        assert [entry["actor_id"] for entry in two["reactions"]] == [second]
        assert require_spatial(await fight.reload())["positions"][MOVER] == pos(11)
        assert [packet["window_id"] for packet in result["packets"] if packet.get("reaction") == STRIKE] == [
            one["window_id"]
        ]
        await activate_as(fight, second)
        result = await fight.command("resolve_phase", {})
        assert result["next"]["waiting_on"]["stage"] == "post_roll"
        assert [packet["window_id"] for packet in result["packets"] if packet.get("reaction") == STRIKE] == [
            two["window_id"]
        ]
        await fight.drain()
    assert rolls.call_count == 3


async def test_ally_does_not_provoke(fight: MawlingHarness) -> None:
    await declare_attack(fight)
    await fight.command("resolve_phase", {})
    state = await fight.reload()
    participant(state, MOVER).type = "companion"
    await fight.persist()
    with (
        patch("check_resolution.dice_roll", return_value=_d20(18)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        result = await fight.command("resolve_phase", {})
    assert result["next"]["waiting_on"]["stage"] == "post_roll"


@pytest.mark.parametrize("fight", ["party"], indirect=True)
@pytest.mark.parametrize("drop", [False, True])
async def test_coincident_spends_stop_on_fall_and_resume_from_completed_strike(
    fight: MawlingHarness, drop: bool
) -> None:
    warrior, target, other = fight.players
    first, second = sorted((warrior, other))
    state = await fight.reload()
    # Start right on both weapon boundaries so the first leg spends nothing.
    require_spatial(state)["positions"].update({MOVER: pos(5), other: pos(0)})
    if drop:
        participant(state, MOVER).hp_current = 1
    await fight.persist()
    if not drop:
        await favor(fight)
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(15), _d20(1), _d20(18)]) as rolls,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)) as damage,
    ):
        result = await advance_to_departure(fight)
        waiting = result["next"]["waiting_on"]
        assert waiting["stage"] == "movement"
        assert {entry["actor_id"] for entry in waiting["reactions"]} == {first, second}
        await activate_as(fight, first)
        await activate_as(fight, second)
        result = await fight.command("resolve_phase", {})
        if drop:
            attack, skipped = [packet for packet in result["packets"] if packet.get("reaction") == STRIKE]
            assert attack["actor_id"] == first
            assert skipped == {
                "reaction": STRIKE,
                "actor_id": second,
                "window_id": waiting["window_id"],
                "target_id": MOVER,
                "resolved": False,
                "reason": "target already fell",
            }
            saved = await fight.reload()
            assert require_spatial(saved)["positions"][MOVER] == pos(5) and participant(saved, MOVER).is_fallen
            assert participant(saved, target).hp_current == 100
            rolls.assert_called_once()
            damage.assert_called_once()
            return
        assert result["fate_offer"]["roller_id"] == first
        await reconnect(fight)
        result = await fight.command("resolve_phase", {})
        assert result["fate_offer"]["roller_id"] == second
        (attack,) = [packet for packet in result["packets"] if packet.get("reaction") == STRIKE]
        assert attack["actor_id"] == first
        assert require_spatial(await fight.reload())["positions"][MOVER] == pos(5)
        await reconnect(fight)
        result = await fight.command("resolve_phase", {})
        assert result["fate_offer"]["roller_id"] == MOVER
        (attack,) = [packet for packet in result["packets"] if packet.get("reaction") == STRIKE]
        assert attack["actor_id"] == second and not attack["hit"]
        assert rolls.call_count == 3
        damage.assert_called_once()


async def test_a_wall_blocks_the_strike_without_blocking_the_approach(fight: MawlingHarness) -> None:
    _, target = fight.players
    state = await fight.reload()
    require_spatial(state)["positions"].update({MOVER: pos(3, 3), target: pos(25, 3)})
    add_wall(state, "wall", "Slate Wall", pos(-5, 1), pos(10, 1))
    await fight.persist()
    with (
        patch("check_resolution.dice_roll", return_value=_d20(18)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        result = await advance_to_departure(fight)
        assert result["next"]["waiting_on"]["stage"] == "post_roll"
    assert require_spatial(await fight.reload())["positions"][MOVER] == pos(20, 3)


async def test_a_full_speed_diagonal_approach_resumes_within_its_allowance(fight: MawlingHarness) -> None:
    # The two legs' floating costs can sum one ulp above the 30-foot allowance on this diagonal.
    state = await fight.reload()
    require_spatial(state)["positions"][fight.players[1]] = pos(30, -27)
    await fight.persist()
    with (
        patch("check_resolution.dice_roll", return_value=_d20(18)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        assert (await advance_to_departure(fight))["next"]["waiting_on"]["stage"] == "movement"
        result = await fight.command("resolve_phase", {})
    attack = next(packet for packet in result["packets"] if packet["actor_id"] == MOVER)
    assert attack["resolved"] and attack["movement_spent_ft"] == pytest.approx(30)
