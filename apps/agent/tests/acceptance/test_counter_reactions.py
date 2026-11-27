from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _damage_die
from acceptance._enemy_opportunity_helpers import move
from acceptance.counter_reactions_harness import (
    RETALIATE,
    RIPOSTE,
    SHIELD_ITEM,
    SIDESTEP,
    WEAPON,
    counter_fight,
    react,
    shield_hits,
    window_for,
)
from acceptance.defensive_reactions_harness import (
    action_packet,
    declare_attacks,
    hp,
    player_row,
    reaction_packet,
    reload_session,
)
from acceptance.test_architect_entomb import favor
from acceptance.test_architect_fight import pos
from acceptance.test_bark_skin import keep_original
from acceptance.test_guardian_intercept import SWORD, tool_receipt
from acceptance.test_opportunity_strike import participant
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_still_anchors import strike

from check_resolution import D20Roll
from combat_spatial import position, require_spatial


@pytest.mark.parametrize("scenario", ["declined", "plain", "resistant", "guardian_falls"])
async def test_retaliating_shield(reset_db_pool, scenario):
    async with counter_fight(RETALIATE, gear=SHIELD_ITEM) as fight:
        reactor = fight.players[0]
        enemy, other = fight.enemies
        state = await fight.reload()
        participant(state, enemy).damage_affinities = {"resistant": ["bludgeoning"]} if scenario == "resistant" else {}
        participant(state, reactor).damage_affinities = {"resistant": ["fire"]}
        initial_hp = 3 if scenario == "guardian_falls" else 100
        participant(state, reactor).hp_current = initial_hp
        before, other_hp = [participant(state, e).hp_current for e in fight.enemies]
        stamina = (await player_row(reactor))["stamina"]["current"]
        shield = await shield_hits(reactor)
        await fight.persist()
        await declare_attacks(fight, reactor, enemy)
        packets = []
        spent = scenario != "declined"
        with (
            patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(15)),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(8)),
            patch("dice.roll", return_value=_damage_die(5)),
        ):
            await window_for(fight, RETALIATE, packets)
            if spent:
                await react(fight, RETALIATE)
            packets += await fight.drain()
        incoming = action_packet(packets, enemy, SWORD)
        assert incoming["damage"] == 8
        assert ("shield" in incoming["durability"]) is spent
        assert await hp(fight) == [max(0, initial_hp - 8), 100]
        assert (await player_row(reactor))["stamina"]["current"] == stamina - 2 * spent
        assert await shield_hits(reactor) == shield - spent
        state = await fight.reload()
        landed = 0 if not spent else 4 if scenario == "resistant" else 8
        assert participant(state, enemy).hp_current == before - landed
        assert participant(state, other).hp_current == other_hp
        if spent:
            receipt = reaction_packet(packets, RETALIATE)
            assert receipt["actor_id"] == reactor and receipt["against_actor_id"] == enemy
            assert receipt["counter_attack"]["damage_type"] == "bludgeoning"
            assert receipt["counter_attack"]["damage"] == landed
            assert receipt["mechanical_effect"] == "shield_durability"


@pytest.mark.parametrize("hit", [True, False])
async def test_riposte(reset_db_pool, hit):
    for spent in (False, True):
        async with counter_fight(RIPOSTE, gear=WEAPON) as fight:
            reactor = fight.players[0]
            enemy = fight.enemies[0]
            before = participant(await fight.reload(), enemy).hp_current
            stamina = (await player_row(reactor))["stamina"]["current"]
            weapon = (await player_row(reactor))["equipment"]["main_hand"]
            await declare_attacks(fight, reactor, enemy)
            packets = []
            counter_roll = 16 if hit else 2
            rolls = iter((1, counter_roll))
            with (
                patch.object(D20Roll, "roll", lambda self, _rng=None, rolls=rolls: self.evaluate(next(rolls))),
                patch("check_resolution_attack.dice_roll", return_value=_damage_die(3)),
            ):
                await window_for(fight, RIPOSTE, packets)
                if spent:
                    await react(fight, RIPOSTE)
                packets += await fight.drain()
            assert not action_packet(packets, enemy, SWORD)["hit"]
            assert await hp(fight) == [100, 100]
            assert (await player_row(reactor))["stamina"]["current"] == stamina - 3 * spent
            landed = 3 + 3 if spent and hit else 0
            assert participant(await fight.reload(), enemy).hp_current == before - landed
            if spent:
                counter = reaction_packet(packets, RIPOSTE)["counter_attack"]
                assert counter["action"] == weapon["name"] and counter["target_id"] == enemy
                assert (counter["roll"], counter["hit"], counter["damage"]) == (counter_roll, hit, landed)
                assert fight.sd.member_state(reactor).weapon_used is True
                assert not fight.sd.member_state(fight.players[1]).weapon_used


@pytest.mark.parametrize(("use_bark", "margin"), [(False, 0), (True, 2), (True, 0)])
async def test_bark_skin_opens_distinct_miss_window(reset_db_pool, use_bark, margin):
    async with counter_fight(RIPOSTE, gear=WEAPON) as fight:
        reactor, ally = fight.players
        enemy = fight.enemies[0]
        state = await fight.reload()
        ally_ac = participant(state, ally).ac
        original_hp = participant(state, enemy).hp_current
        focus = (await player_row(ally))["focus"]["current"]
        bark = "warden_bark_skin"
        await declare_attacks(fight, ally, enemy)
        packets = []
        flipped = use_bark and margin == 0
        with (
            patch.object(
                D20Roll,
                "roll",
                lambda self, _rng=None: self.evaluate(
                    int(self.dc + margin - self.modifier) if self.dc == ally_ac else 16
                ),
            ),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(3)),
        ):
            first = await window_for(fight, bark, packets)
            held_seq = (await fight.reload()).held_actions[0]["seq"]
            if use_bark:
                receipt = await tool_receipt(fight, ally, "activate", {"id": bark})
                assert not receipt.is_error, receipt.output
            result = await fight.command("resolve_phase", {})
            packets += result["packets"]
            miss = result["next"]["waiting_on"]
            if flipped:
                assert miss and miss["window_id"] != first["window_id"]
                assert "on_enemy_miss" in miss["triggers"]
                assert (await fight.reload()).held_actions[0]["seq"] == held_seq
                assert RIPOSTE in {r["id"] for r in miss["reactions"]}
                await react(fight, RIPOSTE)
                packets += await fight.drain()
            else:
                assert miss is None or "on_enemy_miss" not in miss["triggers"]
        attack = action_packet(packets, enemy, SWORD)
        assert attack["target_ac"] == ally_ac + 2 * use_bark
        assert attack["hit"] is not flipped
        assert (await player_row(ally))["focus"]["current"] == focus - 2 * use_bark
        assert await hp(fight) == [100, 100 - attack["damage"]]
        assert sum(p.get("ability_id") == bark for p in packets) == use_bark
        assert participant(await fight.reload(), enemy).hp_current == original_hp - 6 * flipped
        if flipped:
            assert reaction_packet(packets, RIPOSTE)["counter_attack"]["actor_id"] == reactor


@pytest.mark.parametrize("ability", [RETALIATE, RIPOSTE, SIDESTEP], ids=["retaliating_shield", "riposte", "sidestep"])
async def test_counter_survives_fate_reload(reset_db_pool, ability):
    shield = ability == RETALIATE
    riposte = ability == RIPOSTE
    enemy_type = "hollow_knight" if shield or riposte else "bandit"
    gear = SHIELD_ITEM if shield else WEAPON if riposte else None
    async with counter_fight(
        ability, reach=10 if ability == SIDESTEP else 5, gear=gear, enemy_type=enemy_type
    ) as fight:
        reactor, ally = fight.players
        enemy, lookout = fight.enemies
        state = await fight.reload()
        action = participant(state, enemy).action_pool[0]["name"]
        participant(state, enemy).hp_current = 3 if gear else 16
        stamina = (await player_row(reactor))["stamina"]["current"]
        shield_before = await shield_hits(reactor) if shield else 0
        await fight.persist()
        await favor(fight)
        await fight.command(
            "declare_phase",
            {
                "declarations": [
                    {"actor_id": enemy, **strike(reactor, action=action)},
                    {"actor_id": lookout, **strike(ally, action=SWORD)},
                ]
            },
        )
        packets = []
        offers = []
        spent = False
        weapon_use = None
        round_before = state.round_number
        rolls = iter((1, 17, 2, 15) if riposte else (15, 2, 15) if shield else (15, 15))
        with (
            patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(next(rolls))),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
            patch("dice.roll", return_value=_damage_die(5)) as retaliation_die,
        ):
            for _ in range(14):
                result = await fight.command("resolve_phase", {})
                packets += result["packets"]
                for _ in range(6):
                    if not (offer := result.get("fate_offer")):
                        break
                    roll_key = (offer["roll_kind"], offer["roller_id"])
                    if riposte and roll_key == ("attack", lookout):
                        weapon_use = (
                            fight.sd.member_state(reactor).weapon_used,
                            fight.sd.member_state(ally).weapon_used,
                        )
                    if spent and roll_key not in offers:
                        offers.append(roll_key)
                        if offer["roller_id"] == enemy and offer["roll_kind"] == "save" and shield:
                            assert await hp(fight) == [92, 100]
                            assert await shield_hits(reactor) == shield_before - 1
                        if ability == SIDESTEP:
                            assert position((await fight.reload()).spatial, reactor) == pos(10)
                        await reload_session(fight)
                        result = await fight.command("resolve_phase", {})
                    else:
                        result = await keep_original(fight, offer)
                    packets += result["packets"]
                else:
                    pytest.fail("The held roll did not resume.")
                window = result["next"]["waiting_on"]
                if not spent and window and ability in {reaction["id"] for reaction in window["reactions"]}:
                    await react(fight, ability, **({"destination": pos(10)} if ability == SIDESTEP else {}))
                    await reload_session(fight)
                    spent = True
                if (await fight.reload()).round_number != round_before:
                    break
            else:
                pytest.fail("The held counter did not finish the round.")
        assert spent
        original = action_packet(packets, enemy, action)
        assert original["hit"] is not riposte
        assert action_packet(packets, lookout, SWORD)["hit"]
        receipt = reaction_packet(packets, ability)
        assert (await player_row(reactor))["stamina"]["current"] == stamina - (3 if riposte else 2)
        state = await fight.reload()
        if gear:
            assert ("save", enemy) in offers
            counter = receipt["counter_attack"]
            assert not counter["unholy_fortitude"]["success"]
            assert participant(state, enemy).hp_current == 0
            assert counter["target_id"] == enemy and counter["actor_id"] == reactor
            if shield:
                retaliation_die.assert_called_once_with("1d6")
                assert await shield_hits(reactor) == shield_before - 1
                assert await hp(fight) == [92, 96]
            else:
                assert ("attack", reactor) in offers
                assert counter["roll"] == 17 and await hp(fight) == [100, 96]
                assert weapon_use == (True, False)
        else:
            assert ("attack", enemy) in offers
            assert receipt["movement"]["destination"] == position(state.spatial, reactor) == pos(10)
            assert await hp(fight) == [96, 96]


async def test_sidestep_does_not_provoke(reset_db_pool):
    for sidestep in (False, True):
        async with counter_fight(SIDESTEP) as fight:
            reactor, ally = fight.players
            enemy, lookout = fight.enemies
            state = await fight.reload()
            require_spatial(state)["positions"][lookout] = pos(0, 10)
            await fight.persist()
            actions = [{"actor_id": lookout, **strike(ally, action=SWORD)}]
            actions.append({"actor_id": enemy, **strike(reactor, action=SWORD)} if sidestep else move(reactor, 10))
            await fight.command("declare_phase", {"declarations": actions})
            packets = []
            with (
                patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(15)),
                patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
            ):
                if sidestep:
                    await window_for(fight, SIDESTEP, packets)
                    await react(fight, SIDESTEP, destination=pos(10))
                await window_for(fight, "warden_bark_skin", packets)
            state = await fight.reload()
            assert state.reactions_available[enemy]["spent"] is not sidestep
            opportunity = [p for p in packets if p.get("opportunity_attack") and p["actor_id"] == enemy]
            assert [p["damage"] for p in opportunity] == ([] if sidestep else [4])
            assert await hp(fight) == ([100, 100] if sidestep else [96, 100])
            assert position(state.spatial, reactor) == pos(10)
