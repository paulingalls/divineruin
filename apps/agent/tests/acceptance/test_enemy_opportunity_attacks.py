from itertools import chain, repeat
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance._enemy_opportunity_helpers import (
    attack,
    declare,
    move,
    resolve_allies,
    strikes,
)
from acceptance._enemy_opportunity_helpers import (
    fight as fight,
)
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_entomb import favor
from acceptance.test_architect_fight import pos
from acceptance.test_opportunity_strike import participant, reconnect
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory

import db_queries
from combat_spatial import require_spatial


@pytest.mark.parametrize("hit", [True, False])
async def test_move_out_of_enemy_reach(fight: MawlingHarness, hit: bool) -> None:
    mover = fight.players[0]
    await declare(fight, move(mover, 20))
    with (
        patch("check_resolution.dice_roll", return_value=_d20(18 if hit else 1)) as rolls,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        packets = await resolve_allies(fight)
    strike, movement = [packet for packet in packets if packet["actor_id"] in ("bandit", mover)]
    assert strike["opportunity_attack"] and strike["actor_id"] == "bandit"
    assert strike["target_id"] == mover and strike["action"] == "Short Sword"
    assert strike["hit"] is hit and strike["damage"] == (4 if hit else 0)
    assert strike["interrupt_position"] == pos(5)
    assert movement["moved_ft"] == movement["movement_spent_ft"] == 17
    state = await fight.reload()
    assert require_spatial(state)["positions"][mover] == pos(20)
    assert require_spatial(state)["positions"]["bandit"] == pos(0)
    assert state.reactions_available["bandit"]["spent"]
    assert state.first_hostility["bandit"] == "hostile"
    assert mover in state.encounter_facts["attacked"]
    if not hit:
        assert state.encounter_facts["misses"]["bandit"] == [mover]
    rolls.assert_called_once()


ROGUE = {"player": {"class": "rogue"}}
GUARDIAN = {"player": {"class": "guardian", "divine_favor": {"patron": "mortaen", "level": 40, "max": 100}}}


@pytest.mark.parametrize("fight", [ROGUE], indirect=True)
@pytest.mark.parametrize("drop", [False, True])
async def test_strike_precedes_rogue_approach(fight: MawlingHarness, drop: bool) -> None:
    mover = fight.players[0]
    state = await fight.reload()
    if drop:
        participant(state, mover).hp_current = 3
        await fight.persist()
    await declare(fight, attack(mover, "lookout", "Longsword"))
    with (
        patch("check_resolution.dice_roll", return_value=_d20(18)) as rolls,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        packets = await resolve_allies(fight)
    strike, approach = [packet for packet in packets if packet["actor_id"] in ("bandit", mover)]
    assert strike["opportunity_attack"] and strike["interrupt_position"] == pos(5)
    assert approach["attack_resolved"] is not drop
    state = await fight.reload()
    assert require_spatial(state)["positions"][mover] == pos(5 if drop else 20)
    assert rolls.call_count == (1 if drop else 2)
    player = await db_queries.get_player(mover)
    assert player is not None and player["hp"]["current"] == (0 if drop else 96)
    if drop:
        assert participant(state, mover).is_fallen
        assert state.encounter_facts["ally_downers"] == ["bandit"]
        assert participant(state, "lookout").hp_current == 16
    else:
        assert participant(state, "lookout").hp_current < 16


@pytest.mark.parametrize("fight,drop", [({}, False), (ROGUE, True)], indirect=["fight"])
async def test_later_swing_approach_resumes_with_shared_allowance(fight: MawlingHarness, drop: bool) -> None:
    mover = fight.players[0]
    state = await fight.reload()
    warrior = participant(state, mover)
    warrior.enhancers = ["shield_bash"]
    warrior.action_pool[0]["reach"] = 10
    if drop:
        warrior.hp_current = 3
    spatial = require_spatial(state)
    spatial["positions"]["lookout"] = pos(16)
    spatial["positions"]["bandit"] = pos(2)
    spatial["speeds"][mover] = 8
    await fight.persist()
    await declare(fight, attack(mover, "lookout", "Longsword", rider="hide" if drop else ""))

    with (
        patch("check_resolution.dice_roll", return_value=_d20(18)) as rolls,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        paused = await fight.command("resolve_phase", {})
        assert paused["next"]["waiting_on"]["stage"] == "post_roll"
        state = await fight.reload()
        continuation = state.ally_continuation
        assert continuation is not None
        assert continuation["attack"]["summaries"][0]["moved_ft"] == 3
        assert continuation["steps"]["movement_route"]["budget"]["remaining"] == 4
        assert require_spatial(state)["positions"][mover] == pos(7)
        first_hp = participant(state, "lookout").hp_current
        assert first_hp == 16 - continuation["attack"]["summaries"][0]["damage"] < 16
        await reconnect(fight)
        packets = await resolve_allies(fight)
    (strike,) = strikes(packets)
    assert strike["interrupt_position"] == pos(7)
    state = await fight.reload()
    assert rolls.call_count == (2 if drop else 3)
    assert require_spatial(state)["positions"][mover] == pos(7 if drop else 11)
    result = next(packet for packet in packets if packet["actor_id"] == mover)
    assert result["resolved"] is not drop
    if drop:
        assert "cunning_action" not in result
    final_hp = participant(state, "lookout").hp_current
    assert final_hp == (first_hp if drop else first_hp - result["attacks"][1]["damage"])


async def test_explicit_move_drops_at_reach_boundary(fight: MawlingHarness) -> None:
    mover = fight.players[0]
    participant(await fight.reload(), mover).hp_current = 3
    await fight.persist()
    await declare(fight, move(mover, 20))
    with (
        patch("check_resolution.dice_roll", return_value=_d20(18)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        packets = await resolve_allies(fight)
    state = await fight.reload()
    assert participant(state, mover).is_fallen
    assert require_spatial(state)["positions"][mover] == pos(5)
    receipt = next(packet for packet in packets if packet["actor_id"] == mover)
    assert not receipt["resolved"] and receipt["moved_ft"] == 2
    assert strikes(packets)[0]["target_fallen"]


async def test_budget_is_shared_by_departures_and_refreshes_next_round(fight: MawlingHarness) -> None:
    mover, ally = fight.players
    state = await fight.reload()
    require_spatial(state)["positions"][ally] = pos(-4)
    participant(state, mover).initiative = 30
    await fight.persist()
    await declare(fight, move(mover, 20), move(ally, -23))
    with patch("check_resolution.dice_roll", return_value=_d20(1)) as rolls:
        first = strikes(await resolve_allies(fight))
        assert [(blow["actor_id"], blow["target_id"]) for blow in first] == [("bandit", mover)]
        await fight.drain()
        state = await fight.reload()
        require_spatial(state)["positions"][mover] = pos(3)
        await fight.persist()
        await declare(fight, move(mover, 20))
        assert not (await fight.reload()).reactions_available["bandit"]["spent"]
        assert len(strikes(await resolve_allies(fight))) == 1
        assert rolls.call_count == 2


@pytest.mark.parametrize("fight", [ROGUE], indirect=True)
async def test_uncanny_dodge_reloads_and_binds_only_the_opportunity(fight: MawlingHarness) -> None:
    from sample_fixtures import published_types

    import db_mutations

    mover = fight.players[0]
    await declare(fight, move(mover, 20), attack("lookout", mover, "Short Sword"))
    with (
        patch("check_resolution.dice_roll", return_value=_d20(18)) as rolls,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(8)),
        patch("db_mutations.update_player_hp", wraps=db_mutations.update_player_hp) as hp_writes,
    ):
        result = await fight.command("resolve_phase", {})
        waiting = result["next"]["waiting_on"]
        assert waiting["stage"] == "post_roll"
        assert waiting["opportunity_attack"] and waiting["interrupt_position"] == pos(5)
        assert [entry["id"] for entry in waiting["reactions"]] == ["rogue_uncanny_dodge"]
        state = await fight.reload()
        assert require_spatial(state)["positions"][mover] == pos(5)
        assert participant(state, mover).hp_current == 100
        seq = state.held_actions[0]["seq"]
        hp_writes.assert_not_called()

        await reconnect(fight)
        await fight.command("activate", {"id": "rogue_uncanny_dodge"})
        await reconnect(fight)
        state = await fight.reload()
        assert state.open_window is not None and state.open_window["id"] == waiting["window_id"]
        assert state.reactions_available[mover]["held_seq"] == seq
        assert state.reactions_available["bandit"]["held_seq"] is None
        packets = await resolve_allies(fight)
        (strike,) = strikes(packets)
        assert strike["damage"] == 4
        hp_writes.assert_called_once()
        assert rolls.call_count == 1
        assert published_types(fight.sd.room).count("dice_roll") == 1
        state = await fight.reload()
        assert require_spatial(state)["positions"][mover] == pos(20)
        assert all(head["seq"] != seq for head in state.held_actions)
        ordinary = [packet for packet in await fight.drain() if packet["actor_id"] == "lookout"]
    assert len(ordinary) == 1 and ordinary[0]["damage"] == 8
    assert rolls.call_count == hp_writes.call_count == 2


@pytest.mark.parametrize("fight", [GUARDIAN], indirect=True)
@pytest.mark.parametrize("fallen", [False, True])
async def test_mortaen_raises_ac_against_the_opportunity(fight: MawlingHarness, fallen: bool) -> None:
    mover, ally = fight.players
    state = await fight.reload()
    guardian = participant(state, mover)
    if fallen:
        participant(state, ally).hp_current = 0
        participant(state, ally).is_fallen = True
        await fight.persist()
    sword = next(action for action in participant(state, "bandit").action_pool if action["name"] == "Short Sword")
    await declare(fight, move(mover, 20))
    with (
        patch("check_resolution.dice_roll", return_value=_d20(guardian.ac - sword["to_hit"])),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        (strike,) = strikes(await resolve_allies(fight))
    assert strike["attack_total"] == guardian.ac
    assert strike["target_ac"] == guardian.ac + fallen
    assert strike["mortaen_ac_bonus"] == int(fallen)
    assert strike["mortaen_ac_clause_id"] == ("mortaen_threshold_shield" if fallen else None)
    assert strike["hit"] is not fallen and strike["damage"] == (0 if fallen else 4)
    assert require_spatial(await fight.reload())["positions"][mover] == pos(20)


@pytest.mark.parametrize("fight", [{"ally": {"class": "cleric"}}], indirect=True)
async def test_pre_roll_reaction_protects_the_mover(fight: MawlingHarness) -> None:
    from acceptance._enemy_opportunity_helpers import activate_as

    mover, ally = fight.players
    state = await fight.reload()
    ac = participant(state, mover).ac
    await declare(fight, move(mover, 20))
    with patch("check_resolution.dice_roll", return_value=_d20(ac - 4)) as rolls:
        first = await fight.command("resolve_phase", {})
        waiting = first["next"]["waiting_on"]
        assert waiting["stage"] == "pre_roll"
        assert [(entry["actor_id"], entry["id"]) for entry in waiting["reactions"]] == [
            (ally, "cleric_shield_of_faith")
        ]
        rolls.assert_not_called()
        assert participant(await fight.reload(), mover).hp_current == 100
        await activate_as(fight, ally, "cleric_shield_of_faith")
        (strike,) = strikes(await resolve_allies(fight))
    assert strike["target_ac"] == ac + 2 and not strike["hit"]


async def test_hostile_fate_roll_reloads_at_the_boundary(fight: MawlingHarness) -> None:
    mover = fight.players[0]
    await favor(fight)
    await declare(fight, move(mover, 20))
    with (
        patch("check_resolution.dice_roll", return_value=_d20(18)) as rolls,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)) as damage,
    ):
        first = await fight.command("resolve_phase", {})
        assert first["fate_offer"]["roller_id"] == "bandit"
        await reconnect(fight)
        assert require_spatial(await fight.reload())["positions"][mover] == pos(5)
        damage.assert_not_called()
        (strike,) = strikes(await resolve_allies(fight))
    rolls.assert_called_once()
    damage.assert_called_once()
    assert strike["hit"] and strike["damage"] == 4
    assert require_spatial(await fight.reload())["positions"][mover] == pos(20)


@pytest.mark.parametrize("fight", [{**ROGUE, "include_second_bandit": True}], indirect=True)
@pytest.mark.parametrize(
    "rider,face,partial", [("", 18, False), ("disengage", 18, False), ("disengage", 1, False), ("disengage", 18, True)]
)
async def test_cunning_disengage_departure(fight: MawlingHarness, rider: str, face: int, partial: bool) -> None:
    mover = fight.players[0]
    await fight.pool.execute(
        "UPDATE players SET data=jsonb_set(data, '{stamina,current}', '2') WHERE player_id=$1", mover
    )
    state = await fight.reload()
    spatial = require_spatial(state)
    speed = spatial["speeds"][mover]
    if partial:
        spatial["positions"]["lookout"] = pos(3 + speed + 15)
        await fight.persist()
    await declare(fight, attack(mover, "lookout", "Longsword", rider=rider))
    with (
        patch(
            "check_resolution.dice_roll",
            side_effect=chain([_d20(1)] * (0 if rider else 2), [] if partial else [_d20(face)], repeat(_d20(1))),
        ) as rolls,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        if rider:
            result = await fight.command("resolve_phase", {})
            assert result["next"]["waiting_on"] is None
            packets = result["packets"]
        else:
            packets = await resolve_allies(fight)
    assert len(strikes(packets)) == (0 if rider else 2)
    assert rolls.call_count == (0 if rider else 2) + (not partial)
    (receipt,) = (packet for packet in packets if packet["actor_id"] == mover)
    assert receipt["attack_resolved"] is not partial
    if partial:
        assert receipt["movement_spent_ft"] == speed
    else:
        assert receipt["hit"] is (face != 1)
        if rider:
            assert receipt["cunning_action"] == {"rider": rider}
    saved = await fight.reload()
    assert require_spatial(saved)["positions"][mover] == pos(3 + speed if partial else 20)
    for bandit in ("bandit", "second_bandit"):
        assert saved.reactions_available[bandit]["spent"] is (not rider)
    player = await db_queries.get_player(mover)
    assert player is not None and player["hp"]["current"] == 100
    assert player["stamina"]["current"] == (0 if rider else 2)
