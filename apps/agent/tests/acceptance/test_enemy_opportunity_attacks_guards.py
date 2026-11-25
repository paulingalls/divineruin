from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance._enemy_opportunity_helpers import attack, declare, move, resolve_allies, strikes
from acceptance._enemy_opportunity_helpers import fight as fight
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_entomb import favor
from acceptance.test_architect_fight import pos
from acceptance.test_combat_wall_lines import wall
from acceptance.test_opportunity_strike import participant, reconnect
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory
from weapon_fixtures import DAGGER

import db_queries
import reaction_spend
from combat_spatial import require_spatial


@pytest.mark.parametrize(
    "case",
    [
        "able",
        "diagonal",
        "spent",
        "fallen",
        "dead",
        "no_hp",
        "stunned",
        "dormant",
        "ranged",
        "outside",
        "within",
        "boundary",
        "blocked",
    ],
)
async def test_provocation_requires_an_able_enemy_and_a_reach_exit(fight: MawlingHarness, case: str) -> None:
    mover, ally = fight.players
    state = await fight.reload()
    bandit = participant(state, "bandit")
    positions = require_spatial(state)["positions"]
    positions[ally] = pos(0)
    destination = pos(20)
    if case == "diagonal":
        # The exit point of this route lands at 5.000000000000001 ft in floats.
        destination = pos(9, 8)
    elif case == "fallen":
        bandit.is_fallen = True
    elif case == "dead":
        bandit.is_dead = True
    elif case == "no_hp":
        bandit.hp_current = 0
    elif case == "dormant":
        bandit.still_dormant = True
    elif case == "ranged":
        bandit.action_pool = [action for action in bandit.action_pool if action.get("type") == "ranged"]
        bandit.action_ledger.clear()
        positions[mover] = pos(79)
        destination = pos(90)
    elif case == "outside":
        positions[mover] = pos(6)
    elif case == "within":
        destination = pos(4)
    elif case == "boundary":
        destination = pos(5)
    elif case == "blocked":
        wall(state, 1)
    elif case == "spent":
        state.reactions_available[bandit.id] = {**reaction_spend.unspent(), "spent": True}
    await fight.persist()
    await declare(fight, {**move(mover, 0), "destination": destination})
    if case == "stunned":
        participant(await fight.reload(), "bandit").conditions = [{"type": "stunned", "duration": 2, "source": "test"}]
        await fight.persist()
    with patch("check_resolution.dice_roll", return_value=_d20(1)) as rolls:
        opportunities = strikes(await resolve_allies(fight))
    state = await fight.reload()
    assert require_spatial(state)["positions"][mover] == destination
    assert rolls.call_count == len(opportunities) == (case in ("able", "diagonal"))
    assert state.reactions_available[bandit.id]["spent"] is (case in ("able", "diagonal", "spent"))
    assert not state.reactions_available[ally]["spent"]


@pytest.mark.parametrize(
    "fight,destination,variant,expected",
    [
        ({"bandit": "hollow_mawling"}, 20, "catalog", "Claw"),
        ({"bandit": "hollow_mawling"}, 20, "reordered", "Lunge"),
        ({"bandit": "hollow_mawling"}, 9, "catalog", None),
        ({"bandit": "dire_bear"}, 20, "catalog", "Claw"),
        ({"bandit": "hollow_mawling"}, 20, "higher_printed", "Lunge"),
        ({"bandit": "hollow_mawling"}, 20, "higher_with_bonus", "Lunge"),
        ({"bandit": "hollow_mawling"}, 9, "long_reach_spent", "Dissolution Maw"),
    ],
    indirect=["fight"],
)
async def test_catalog_melee_reach_and_damage_order(
    fight: MawlingHarness, destination: int, variant: str, expected: str | None
) -> None:
    mover = fight.players[0]
    state = await fight.reload()
    require_spatial(state)["positions"][mover] = pos(5)
    if variant != "catalog":
        reactor = participant(state, "bandit")
        pool = reactor.action_pool
        claw = next(i for i, action in enumerate(pool) if action["name"] == "Claw")
        lunge = next(i for i, action in enumerate(pool) if action["name"] == "Lunge")
        if variant == "reordered":
            pool[claw], pool[lunge] = pool[lunge], pool[claw]
        elif variant == "higher_printed":
            pool[lunge]["damage"] = "1d6+4"
        elif variant == "higher_with_bonus":
            pool[lunge].update(damage="1d6+1", bonus_damage={"dice": "1d4", "damage_type": "poison"})
        elif variant == "long_reach_spent":
            for index in (claw, lunge):
                action = pool[index]
                action["recharge"] = {"kind": "encounter", "uses": 1}
                reactor.action_ledger[action["name"].casefold()] = {"remaining": 0, "round": state.round_number}
    await fight.persist()
    await declare(fight, move(mover, destination))
    with patch("check_resolution.dice_roll", return_value=_d20(1)) as rolls:
        opportunities = strikes(await resolve_allies(fight))
    assert [blow["action"] for blow in opportunities] == ([expected] if expected else [])
    assert rolls.call_count == (2 if expected == "Lunge" else int(expected is not None))
    if expected is not None:
        assert opportunities[0]["interrupt_position"] == pos(5 if variant == "long_reach_spent" else 10)
        assert "composite" not in opportunities[0]


@pytest.mark.parametrize("coincident", [False, True])
@pytest.mark.parametrize("drop", [False, True])
async def test_each_exit_resumes_once_in_route_order(fight: MawlingHarness, coincident: bool, drop: bool) -> None:
    mover = fight.players[0]
    state = await fight.reload()
    require_spatial(state)["positions"]["lookout"] = pos(-1e-12 if coincident else 2)
    if drop:
        participant(state, mover).hp_current = 3
    await fight.persist()
    await declare(fight, move(mover, 20))

    with (
        patch("check_resolution.dice_roll", return_value=_d20(18)) as rolls,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        first = await fight.command("resolve_phase", {})
        first_window = first["next"]["waiting_on"]
        assert first_window["actor_id"] == "bandit"
        assert not strikes(first["packets"])
        assert require_spatial(await fight.reload())["positions"][mover] == pytest.approx(pos(5))
        await reconnect(fight)
        if drop:
            (blow,) = strikes(await resolve_allies(fight))
            assert blow["actor_id"] == "bandit" and blow["target_fallen"]
        else:
            second = await fight.command("resolve_phase", {})
            (blow,) = strikes(second["packets"])
            assert blow["actor_id"] == "bandit"
            second_window = second["next"]["waiting_on"]
            assert second_window["actor_id"] == "lookout" and second_window["window_id"] != first_window["window_id"]
            assert require_spatial(await fight.reload())["positions"][mover] == pytest.approx(
                pos(5 if coincident else 7)
            )
            await reconnect(fight)
            (blow,) = strikes(await resolve_allies(fight))
            assert blow["actor_id"] == "lookout"
    state = await fight.reload()
    assert rolls.call_count == (1 if drop else 2)
    assert require_spatial(state)["positions"][mover] == pytest.approx(pos(5 if drop else 20))
    assert state.reactions_available["lookout"]["spent"] is not drop


@pytest.mark.parametrize("fight", [{"bandit": "hollow_veilrender"}], indirect=True)
async def test_opportunity_leaves_turn_start_effects_for_the_normal_turn(fight: MawlingHarness) -> None:
    mover = fight.players[0]
    state = await fight.reload()
    veilrender = participant(state, "bandit")
    veilrender.hp_current -= 20
    hp = veilrender.hp_current
    await fight.persist()
    await declare(fight, move(mover, 20))
    with patch("check_resolution.dice_roll", return_value=_d20(18)):
        (strike,) = strikes(await resolve_allies(fight))
    state = await fight.reload()
    assert strike["action"] == "Crushing Mass"
    assert participant(state, "bandit").hp_current == hp
    assert participant(state, "bandit").veilrender_turn_round != state.round_number
    packets = await fight.drain()
    effects = [e for p in packets if p["actor_id"] == "bandit" for e in p.get("turn_start_effects", [])]
    (regeneration,) = [e for e in effects if e["effect"] == "regeneration"]
    assert regeneration["healed"] == 10
    assert participant(await fight.reload(), "bandit").hp_current == hp + 10


async def test_cunning_disengage_requires_ownership(fight: MawlingHarness) -> None:
    mover = fight.players[0]
    player = await db_queries.get_player(mover)
    before = (await fight.reload()).to_dict()
    result = await fight.command(
        "declare_phase", {"declarations": [attack(mover, "lookout", "Longsword", rider="disengage")]}, error=True
    )
    assert "hasn't learned Cunning Action" in result
    assert (await fight.reload()).to_dict() == before
    assert await db_queries.get_player(mover) == player


@pytest.mark.parametrize("fight", [{"player": {"class": "rogue"}}], indirect=True)
async def test_cunning_disengage_survives_fate_reload_and_later_approach(fight: MawlingHarness) -> None:
    mover = fight.players[0]
    await favor(fight)
    before = await db_queries.get_player(mover)
    assert before is not None
    state = await fight.reload()
    rogue = participant(state, mover)
    rogue.enhancers = ["shield_bash"]
    rogue.action_pool[0]["reach"] = 10
    spatial = require_spatial(state)
    spatial["positions"]["lookout"] = pos(16)
    spatial["positions"]["bandit"] = pos(2)
    spatial["speeds"][mover] = 7
    participant(state, "lookout").hp_current = 100
    await fight.persist()
    await declare(fight, attack(mover, "lookout", DAGGER["name"], rider="disengage"))

    with (
        patch("check_resolution.dice_roll", return_value=_d20(18)) as rolls,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        paused = await fight.command("resolve_phase", {})
        assert (paused["fate_offer"]["roll_kind"], paused["fate_offer"]["roller_id"]) == ("attack", mover)
        assert not strikes(paused["packets"])
        assert require_spatial(await fight.reload())["positions"][mover] == pos(6)
        assert await db_queries.get_player(mover) == before
        await reconnect(fight)
        resumed = await fight.command("resolve_phase", {})
        assert resumed["next"]["waiting_on"] is None
        assert "fate_offer" not in resumed
        packets = resumed["packets"]
    assert not strikes(packets)
    rolls.assert_called_once()
    (result,) = (packet for packet in packets if packet["actor_id"] == mover)
    assert [swing["moved_ft"] for swing in result["attacks"]] == [3, 4]
    assert result["attacks"][1]["attack_resolved"] is False
    assert require_spatial(await fight.reload())["positions"][mover] == pos(10)
    after = await db_queries.get_player(mover)
    assert after is not None and after["stamina"]["current"] == before["stamina"]["current"] - 2


@pytest.mark.parametrize("fight", [{"bandit": "hollow_knight"}], indirect=True)
async def test_opportunity_critical_save_spends_pending_rally(fight: MawlingHarness) -> None:
    from _zhael_marshal_rally_fixtures import bonus, pending

    mover, marshal = fight.players
    pending(await fight.reload(), mover, marshal)
    await fight.persist()
    await declare(fight, move(mover, 20))
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(20), _d20(11)]),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        (strike,) = strikes(await resolve_allies(fight))
    save = strike["critical_save"]
    assert (strike["action"], strike["critical"], strike.get("condition_inflicted")) == ("Corrupted Blade", True, None)
    assert (save["roll"], save["total"], save["success"]) == (11, 14, True)
    assert save["rally_bonuses"] == [bonus(marshal, mover)]
    assert (await fight.reload()).encounter_facts["rally_pending"] == {}
