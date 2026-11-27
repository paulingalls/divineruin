from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _damage_die
from acceptance.counter_reactions_harness import (
    RETALIATE,
    RIPOSTE,
    SHIELD_ITEM,
    SIDESTEP,
    WEAPON,
    counter_fight,
    react,
    window_for,
)
from acceptance.defensive_reactions_harness import action_packet, declare_attacks, hp, player_row, reaction_packet
from acceptance.test_architect_entomb import favor
from acceptance.test_architect_fight import pos
from acceptance.test_guardian_intercept import SWORD, tool_receipt
from acceptance.test_opportunity_strike import participant
from acceptance.test_shadow_step_guards import trap
from acceptance.test_still_anchors import declare, strike
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory

from check_resolution import D20Roll
from combat_spatial import position, require_spatial
from combat_structures import add_wall


@pytest.mark.parametrize("reach", [5, 10])
async def test_sidestep_reach(reset_db_pool, reach):
    for spent in (False, True) if reach == 5 else (True,):
        async with counter_fight(SIDESTEP, reach=reach) as fight:
            reactor = fight.players[0]
            enemy = fight.enemies[0]
            stamina = (await player_row(reactor))["stamina"]["current"]
            await declare_attacks(fight, reactor, enemy)
            packets = []
            with (
                patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(20)),
                patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
            ):
                await window_for(fight, SIDESTEP, packets)
                if spent:
                    await react(fight, SIDESTEP, destination=pos(10))
                packets += await fight.drain()
            escaped = spent and reach == 5
            attack = action_packet(packets, enemy, SWORD)
            assert (attack["hit"], attack["damage"]) == (not escaped, 0 if escaped else 8)
            assert await hp(fight) == [100 if escaped else 92, 100]
            state = await fight.reload()
            assert position(state.spatial, reactor) == pos(10 if spent else 5)
            assert position(state.spatial, enemy) == pos(0)
            assert (await player_row(reactor))["stamina"]["current"] == stamina - 2 * spent
            if spent:
                receipt = reaction_packet(packets, SIDESTEP)
                assert receipt["movement"]["moved_ft"] == 5
                assert "reach" in receipt["reason"]


async def test_escaped_sidestep_skips_fate_offer(reset_db_pool):
    async with counter_fight(SIDESTEP) as fight:
        reactor = fight.players[0]
        enemy = fight.enemies[0]
        await declare_attacks(fight, reactor, enemy)
        with patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(15)):
            await window_for(fight, SIDESTEP, [])
            await react(fight, SIDESTEP, destination=pos(10))
            await favor(fight)
            result = await fight.command("resolve_phase", {})
        assert not result.get("fate_offer")
        assert not action_packet(result["packets"], enemy, SWORD)["hit"]


@pytest.mark.parametrize(
    ("obstacle", "reason"),
    [("wall", "blocked"), ("occupied", "occupied"), ("difficult", "exceeds speed"), ("pit", "pit")],
    ids=["wall", "occupied", "difficult", "pit"],
)
async def test_sidestep_blocked(reset_db_pool, obstacle, reason):
    async with counter_fight(SIDESTEP, enemy_type="hollow_architect" if obstacle == "pit" else "bandit") as fight:
        reactor = fight.players[0]
        enemy, *lookouts = fight.enemies
        state = await fight.reload()
        spatial = require_spatial(state)
        if obstacle == "wall":
            add_wall(state, "barrier", "Stone wall", pos(7, -5), pos(7, 5))
        elif obstacle == "occupied":
            spatial["positions"][lookouts[0]] = pos(10)
        elif obstacle == "pit":
            trap(state, reactor)
            assert state.architect_encounter is not None
            state.architect_encounter["floors"]["test_floor"] = {"min": pos(3, -2), "max": pos(7, 2)}
            for area in spatial["movement_areas"].values():
                area["center"] = pos(-100)
        else:
            participant(state, reactor).choir_movement_round = state.round_number
            spatial.setdefault("movement_areas", {})["mud"] = {
                "kind": "difficult_terrain",
                "shape": "rectangle",
                "min": pos(5, -2),
                "max": pos(11, 2),
                "excluded_actor_ids": [],
            }
        await fight.persist()
        action = "Construct Slam" if obstacle == "pit" else SWORD
        await declare(fight, actor_id=enemy, **strike(reactor, action=action))
        packets = []
        with (
            patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(15)),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
        ):
            await window_for(fight, SIDESTEP, packets)
            before = await fight.snapshot()
            receipt = await tool_receipt(fight, reactor, "activate", {"id": SIDESTEP, "destination": pos(10)})
            assert await fight.snapshot() == before
            assert receipt.is_error and reason in receipt.output
            packets += await fight.drain()
        attack = action_packet(packets, enemy, action)
        assert attack["hit"]
        if obstacle != "pit":
            assert position((await fight.reload()).spatial, reactor) == pos(5)
            assert await hp(fight) == [96, 100]


@pytest.mark.parametrize(
    ("selection", "reason"),
    [
        ({}, "destination point"),
        ({"destination": {"start": pos(5), "end": pos(10)}}, "destination point"),
        ({"destination": pos(10), "target_id": "bandit"}, "entity target"),
        ({"destination": pos(11)}, "exceeds speed"),
    ],
    ids=["missing", "wall_endpoints", "entity_selector", "too_far"],
)
async def test_sidestep_selector_refused(reset_db_pool, selection, reason):
    async with counter_fight(SIDESTEP) as fight:
        await declare_attacks(fight, fight.players[0], fight.enemies[0])
        await window_for(fight, SIDESTEP, [])
        before = await fight.snapshot()
        receipt = await tool_receipt(fight, fight.players[0], "activate", {"id": SIDESTEP, **selection})
        assert await fight.snapshot() == before
        assert receipt.is_error and reason in receipt.output


@pytest.mark.parametrize(
    ("reaction", "restriction"),
    [
        (RETALIATE, "ranged"),
        (RETALIATE, "no-shield"),
        (SIDESTEP, "ranged"),
        (RIPOSTE, "ranged"),
        (RIPOSTE, "weapon"),
        (RIPOSTE, "reach"),
        (RIPOSTE, "line"),
    ],
    ids=[
        "shield-ranged",
        "shield-unequipped",
        "sidestep-ranged",
        "riposte-ranged",
        "riposte-ranged-weapon",
        "riposte-out-of-reach",
        "riposte-blocked-line",
    ],
)
async def test_counter_refused(reset_db_pool, reaction, restriction):
    gear = {"weapon": "hunting_bow", "no-shield": None}.get(
        restriction, SHIELD_ITEM if reaction == RETALIATE else WEAPON
    )
    ranged = restriction == "ranged"
    riposte = reaction == RIPOSTE
    ally_class = "skirmisher" if riposte else "guardian"
    async with counter_fight(reaction, ranged=ranged, gear=gear, ally_archetype=ally_class) as fight:
        reactor, ally = fight.players
        enemy = fight.enemies[0]
        state = await fight.reload()
        before_hp = participant(state, enemy).hp_current
        target = ally if riposte else reactor
        if not riposte:
            require_spatial(state)["positions"][ally] = pos(5, 5)
        if restriction == "reach":
            require_spatial(state)["positions"][reactor] = pos(8)
        if restriction == "line":
            add_wall(state, "screen", "Stone wall", pos(2.5, -2), pos(2.5, 2))
        await fight.persist()
        await declare_attacks(fight, target, enemy)
        packets = []
        selectors = {"destination": pos(10)} if reaction == SIDESTEP else {}
        reason = {"weapon": "equipped melee", "no-shield": "equipped shield", "reach": "melee reach", "line": "blocked"}
        with (
            patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(1 if riposte else 15)),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
        ):
            for _ in range(6):
                result = await fight.command("resolve_phase", {})
                packets += result["packets"]
                progress = await fight.reload()
                window = result["next"]["waiting_on"]
                if (window and window["stage"] == "post_roll") or progress.round_number != state.round_number:
                    break
            else:
                pytest.fail("The hostile attack did not resolve or open a window.")
            offers = window["reactions"] if window else []
            assert any(p["id"] == reaction and p["actor_id"] == reactor for p in offers) is (restriction == "no-shield")
            before = await fight.snapshot()
            receipt = await tool_receipt(fight, reactor, "activate", {"id": reaction, **selectors})
            assert await fight.snapshot() == before
            assert receipt.is_error
            if restriction in reason:
                assert reason[restriction] in receipt.output
            if progress.round_number == state.round_number:
                packets += await fight.drain()
        assert action_packet(packets, enemy, SWORD)["hit"] is not riposte
        assert await hp(fight) == ([100, 100] if riposte else [96, 100])
        assert participant(await fight.reload(), enemy).hp_current == before_hp
