"""Nature's Grasp through the registered combat and activation tools."""

from unittest.mock import MagicMock, patch

import pytest
from acceptance.defensive_reactions_harness import (
    action_packet,
    defense_fight,
    player_row,
    reaction_packet,
    reload_session,
    spend,
)
from acceptance.disruption_reactions_harness import dice
from acceptance.test_architect_fight import pos
from acceptance.test_guardian_intercept import SWORD
from acceptance.test_opportunity_strike import participant
from acceptance.test_slippery_restrain import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_spell_bless_lifecycle import leave
from acceptance.test_spell_reaction_offers import resources
from acceptance.test_still_anchors import strike
from creature_combat_helpers import participant as catalog_participant
from test_aelora_gift import _live_party

from check_resolution import D20Roll
from combat_spatial import require_spatial
from creature_catalog import query_creature_by_id
from creature_combat import translate_creature

GRASP = "primal_natures_grasp"


async def depart_guest(fight, guest: str) -> None:
    previous_owner = fight.sd.multiplayer_owner
    lifecycle = _live_party(fight.sd, *fight.players)
    try:
        await lifecycle.authorize(guest)
        await leave(fight.sd, guest, room_io=MagicMock())
        fight.players.remove(guest)
    finally:
        await lifecycle.aclose()
        fight.sd.multiplayer_owner = previous_owner


@pytest.mark.parametrize(
    "route",
    [
        pytest.param(dict(terrain="forest", origin=35, target=5, endpoint=10, face=4, stopped=True), id="stopped"),
        pytest.param(dict(terrain="forest", origin=35, target=5, endpoint=10, face=17, lookout=True), id="resisted"),
        pytest.param(dict(terrain="city", origin=35, target=5, endpoint=10), id="city"),
        pytest.param(dict(terrain="forest", origin=5, target=40, endpoint=35), id="outside"),
        pytest.param(dict(terrain="forest", origin=35, target=25, endpoint=30, face=17), id="edge"),
    ],
)
async def test_held_approach(reset_db_pool, route):
    origin, endpoint, face = route["origin"], route["endpoint"], route.get("face", 4)
    offered, stopped = "face" in route, route.get("stopped", False)
    async with defense_fight("druid", ally_archetype="druid", library=((0, GRASP),)) as fight:
        caster, ally = fight.players
        mover = fight.enemies[0]
        state = await fight.reload()
        state.terrain = route["terrain"]
        positions = require_spatial(state)["positions"]
        positions.update({ally: pos(route["target"]), mover: pos(origin)})
        declarations = [{"actor_id": mover, **strike(ally, action=SWORD)}]
        if route.get("lookout"):
            lookout = fight.enemies[1]
            positions[lookout] = pos(-15)
            declarations.append({"actor_id": lookout, **strike(caster, action=SWORD)})
        await fight.persist()
        focus, resonance = await resources(fight, caster)
        await fight.command("declare_phase", {"declarations": declarations})
        with patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(face)):
            await fight.command("resolve_phase", {})
            first = await fight.command("resolve_phase", {})
            packets = first["packets"]
            if offered:
                window = first["next"]["waiting_on"]
                assert window and window["stage"] == "movement" and {r["id"] for r in window["reactions"]} == {GRASP}
                await reload_session(fight)
                state = await fight.reload()
                assert state.open_window and state.open_window["id"] == window["window_id"]
                head = state.held_actions[0]
                assert head["opportunity_approach"]["endpoint"] == pos(endpoint)
                assert require_spatial(state)["positions"][mover] == pos(origin)
                assert head["roll"] is None
                cast = await fight.command("activate", {"id": GRASP})
                await reload_session(fight)
                spend = (await fight.reload()).reactions_available[caster]
                assert (spend["held_seq"], spend["window_id"], spend["stage"]) == (
                    head["seq"],
                    window["window_id"],
                    "movement",
                )
                packets += await fight.drain()
                receipt = reaction_packet(packets, GRASP)
                assert (receipt["actor_id"], receipt["target_id"], receipt["window_id"]) == (
                    caster,
                    mover,
                    window["window_id"],
                )
                save = receipt["save"]
                assert (save["attribute"], save["roll"], save["success"]) == ("strength", face, not stopped)
                assert (receipt.get("condition_inflicted") == "restrained") is stopped
                assert cast["resonance_generated"] == 0
                if stopped:
                    assert any(
                        p.get("actor_id") == mover and p.get("attack_resolved") is False and p.get("moved_ft") == 0
                        for p in packets
                    )
            else:
                assert first["next"]["waiting_on"] is None
                assert all(p.get("ability_id") != GRASP for p in packets)
            await reload_session(fight)
            state = await fight.reload()
            positions = require_spatial(state)["positions"]
            assert positions[mover] == pos(origin if stopped else endpoint)
            if route.get("lookout"):
                assert positions[fight.enemies[1]] == pos(-5)
            assert not any(c["type"] == "restrained" for c in participant(state, mover).conditions)
            assert await resources(fight, caster) == (focus - (2 if offered else 0), resonance)


@pytest.mark.parametrize("target_departs", [False, True], ids=["sibling-and-next-turn", "target-departs"])
async def test_restraint_ends_with_the_movers_turn(reset_db_pool, target_departs):
    async with defense_fight("druid", "hollow_mawling", ally_archetype="bard", library=((0, GRASP),)) as fight:
        caster, bard = fight.players
        mover = fight.enemies[0]
        state = await fight.reload()
        row = await query_creature_by_id("bandit")
        translated = translate_creature(row, encounter_id=state.encounter_id, enemy_id="lookout", role="standard")
        lookout = catalog_participant(translated)
        lookout.initiative = 20
        state.participants.append(lookout)
        state.initiative_order.insert(1, lookout.id)
        spatial = state.spatial
        assert spatial is not None
        spatial["positions"].update({mover: pos(35), bard: pos(35, 5), lookout.id: pos(5)})
        spatial["speeds"][lookout.id] = translated["speed"]
        await fight.persist()
        focus, _ = await resources(fight, caster)
        composite = fight.composite([caster, bard])
        await fight.command(
            "declare_phase",
            {
                "declarations": [
                    composite,
                    {"actor_id": lookout.id, **strike(caster if target_departs else bard, action=SWORD)},
                ]
            },
        )
        with dice(4):
            await spend(fight, GRASP, stage="movement", cost=2)
            pending = await fight.command("resolve_phase", {})
        assert pending["next"]["waiting_on"]["stage"] == "pre_roll"
        assert reaction_packet(pending["packets"], GRASP)["condition_inflicted"] == "restrained"
        await reload_session(fight)
        state = await fight.reload()
        assert require_spatial(state)["positions"][mover] == pos(35)
        assert any(c["source"] == GRASP for c in participant(state, mover).conditions)
        assert (await resources(fight, caster))[0] == focus - 2
        if target_departs:
            await depart_guest(fight, bard)
            await reload_session(fight)
            with dice(18, 18):
                packets = await fight.drain()
            assert any(p.get("actor_id") == mover and p.get("reason") == "The target left the fight." for p in packets)
            assert any(p.get("actor_id") == lookout.id and p.get("hit") for p in packets)
            assert all(c["source"] != GRASP for c in participant(await fight.reload(), mover).conditions)
            return

        before = (await player_row(bard))["hp"]["current"]
        with dice(18, 3):
            next_enemy = await fight.command("resolve_phase", {})
        blow = action_packet(next_enemy["packets"], mover, "Dissolution Maw")
        assert (blow["roll"], blow["hit"], blow["damage"]) == (3, False, 0)
        assert (await player_row(bard))["hp"]["current"] == before
        await reload_session(fight)
        state = await fight.reload()
        assert state.open_window and state.open_window["actor_id"] == lookout.id
        assert all(c["source"] != GRASP for c in participant(state, mover).conditions)
        with dice(3, 3, 3):
            await fight.drain()
        require_spatial(state := await fight.reload())["positions"][caster] = pos(30)
        await fight.persist()
        await fight.command("declare_phase", {"declarations": [composite]})
        with dice(18, 3, 18, 3):
            packets = await fight.drain()
        blow = action_packet(packets, mover, "Claw")
        assert (blow["roll"], blow["hit"]) == (18, True)
