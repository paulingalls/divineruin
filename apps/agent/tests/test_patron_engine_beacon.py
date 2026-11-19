from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from _patron_engine_fixtures import configure
from _zhael_fate_fixtures import attack, defend, game_tools
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.test_kaelen_iron_resolve_capstone import required_player
from test_aelora_gift import _live_party

import conditions
import db_mutations
from combat_end import end_combat
from combat_turn import declare_phase, resolve_phase
from mode_tools import enter_mode

BEACON = "orenthel_beacon"
HOLLOW_A = "shadeling_a"
HOLLOW_B = "shadeling_b"
BANDIT = "bandit"
SOURCE = "attack_disadvantage_source"


@asynccontextmanager
async def beacon_fight(world, *, guest_patron="none", host_class="warrior"):
    for index, (patron, archetype) in enumerate((("orenthel", host_class), (guest_patron, "warrior"))):
        await configure(
            world,
            patron,
            archetype,
            index=index,
            level=5,
            speed=30,
            ac=14,
            hp={"current": 100, "max": 100},
            stamina={"current": 10, "max": 10},
            divine_favor={"patron": patron, "level": 0, "max": 100},
        )
    session = world.ctx.userdata
    call = game_tools(session, enter_mode, declare_phase, resolve_phase, end_combat)
    actors = {HOLLOW_A: "hollow_shadeling", HOLLOW_B: "hollow_shadeling", BANDIT: "bandit"}
    encounter = {
        "id": "beacon_test",
        "name": "Beacon test",
        "recommended_party_level": 5,
        "enemies": [
            {"id": actor_id, "creature_id": creature_id, "role": "standard"} for actor_id, creature_id in actors.items()
        ],
        "scene_placement": {
            "party_start": {"x": 0, "y": 0, "z": 0},
            "companion_start": {"x": 0, "y": 0, "z": 0},
            "actors": {actor: {"x": 5, "y": 0, "z": 0} for actor in actors},
            "locations": {},
            "zones": {},
        },
    }
    with patch("db_content_queries.get_encounter_template", new=AsyncMock(return_value=encounter)):
        await call("enter_mode", mode="combat", encounter_id=encounter["id"])
    state = session.combat_state
    try:
        enemies = {p.id: p for p in state.participants if p.type == "enemy"}
        assert {actor_id: p.creature_id for actor_id, p in enemies.items()} == actors
        assert {actor_id for actor_id, p in enemies.items() if p.hollow is not None} == {HOLLOW_A, HOLLOW_B}
        yield call
    finally:
        await db_mutations.delete_combat_state(state.combat_id, conn=world.pool)


async def declare(call, state, targets):
    declarations = []
    for participant in state.participants:
        if participant.id in targets:
            name = "Short Sword" if participant.id == BANDIT else "Corrosive Touch"
            action = next(action["name"] for action in participant.action_pool if action["name"] == name)
            declarations.append({**attack(participant.id, targets[participant.id]), "action": action})
        else:
            declarations.append(defend(participant.id))
    await call("declare_phase", declarations=declarations)


def attack_packets(result):
    return [packet for packet in result.get("packets", []) if "hit" in packet]


async def drain(call, session, round_number):
    packets = []
    for _ in range(12):
        result = await call("resolve_phase")
        packets.extend(attack_packets(result))
        if session.combat_state.round_number > round_number:
            return packets
    pytest.fail("Resolution failed to finish the round")


@asynccontextmanager
async def rolled_round(call, session, target, attacks):
    state = session.combat_state
    await declare(call, state, dict.fromkeys(attacks, target))
    initial = await call("resolve_phase")
    assert not attack_packets(initial)
    ordered_attackers = [head["actor_id"] for head in session.combat_state.held_actions if head["actor_id"] in attacks]
    assert sorted(ordered_attackers) == sorted(attacks)
    faces = [face for actor in ordered_attackers for face in attacks[actor]]
    rolls = iter(faces)

    def roll(notation, **_):
        assert notation == "d20"
        face = next(rolls, None)
        assert face is not None, f"Extra d20 in the round against {target}: {attacks}"
        return _d20(face)

    with (
        patch("check_resolution.dice_roll", side_effect=roll) as dice,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(2)),
    ):
        yield state.round_number
        assert dice.call_count == len(faces)


async def expect_round(call, session, target, attacks, expected):
    async with rolled_round(call, session, target, attacks) as round_number:
        packets = await drain(call, session, round_number)
    assert len(packets) == len(expected)
    assert {p["actor_id"]: (p["roll"], p["hit"], p.get(SOURCE)) for p in packets} == expected


async def independent_attackers(world):
    session = world.ctx.userdata
    host, guest = world.ids
    async with beacon_fight(world) as call:
        await expect_round(call, session, guest, {HOLLOW_A: [19]}, {HOLLOW_A: (19, True, None)})
        await expect_round(
            call,
            session,
            host,
            {HOLLOW_A: [18, 3], HOLLOW_B: [19, 15], BANDIT: [17]},
            {HOLLOW_A: (3, False, "Beacon"), HOLLOW_B: (15, True, "Beacon"), BANDIT: (17, True, None)},
        )
        saved = await db_mutations.load_combat_state(session.combat_state.combat_id, conn=world.pool)
        assert saved is not None and required_player(saved, host).orenthel_beacon
        session.combat_state = saved
        await expect_round(
            call,
            session,
            host,
            {HOLLOW_A: [12], HOLLOW_B: [13]},
            {HOLLOW_A: (12, False, None), HOLLOW_B: (13, True, None)},
        )
        assert saved.beacon_attacks == {HOLLOW_A: [host], HOLLOW_B: [host]}
        await call("end_combat", outcome="fled")
    async with beacon_fight(world) as call:
        await expect_round(call, session, host, {HOLLOW_A: [19, 15]}, {HOLLOW_A: (15, True, "Beacon")})


async def protected_pair(world):
    session = world.ctx.userdata
    host, guest = world.ids
    async with beacon_fight(world, guest_patron="orenthel") as call:
        player = required_player(session.combat_state, guest)
        player.conditions = conditions.apply_condition(player.conditions, "prone", source=HOLLOW_B)
        await expect_round(call, session, guest, {HOLLOW_A: [15]}, {HOLLOW_A: (15, True, "Beacon")})
        player = required_player(session.combat_state, guest)
        player.conditions = conditions.remove_condition(player.conditions, "prone")
        await expect_round(call, session, host, {HOLLOW_A: [18, 14]}, {HOLLOW_A: (14, True, "Beacon")})
        for target in (guest, host):
            await expect_round(call, session, target, {HOLLOW_A: [16]}, {HOLLOW_A: (16, True, None)})


async def prepared_and_held(world):
    session = world.ctx.userdata
    host, guest = world.ids
    lifecycle = _live_party(session, host, guest)
    try:
        async with beacon_fight(world, guest_patron="zhael", host_class="rogue") as call:
            state = session.combat_state
            combat_id = state.combat_id
            assert "rogue_uncanny_dodge" in required_player(state, host).reaction_ids
            async with rolled_round(call, session, host, {HOLLOW_A: [19, 15]}) as round_number:
                for _ in range(5):
                    result = await call("resolve_phase")
                    assert not attack_packets(result)
                    if "fate_offer" in result:
                        break
                else:
                    pytest.fail("Resolution never offered Fate")
                offer = result["fate_offer"]
                assert offer["die"] == 15 and offer["roller_id"] == HOLLOW_A and offer["eligible_followers"] == [guest]
                saved = await db_mutations.load_combat_state(combat_id, conn=world.pool)
                assert saved is not None
                prepared = saved.held_actions[0]["fate_attack"]["prepared"]
                assert prepared["d20"]["disadvantage"] and prepared[SOURCE] == "Beacon"
                assert saved.beacon_attacks == {}
                session.combat_state = saved

                settled = await call("resolve_phase")
                waiting = settled["next"]["waiting_on"]
                assert waiting["stage"] == "post_roll" and "on_hit" in waiting["triggers"]
                assert not attack_packets(settled)
                saved = await db_mutations.load_combat_state(combat_id, conn=world.pool)
                assert saved is not None
                assert saved.held_actions[0]["roll"]["attack_result"][SOURCE] == "Beacon"
                assert saved.beacon_attacks == {HOLLOW_A: [host]}
                assert required_player(saved, host).hp_current == 100
                session.combat_state = saved
                packets = await drain(call, session, round_number)
                assert [(p["roll"], p["hit"], p.get(SOURCE)) for p in packets] == [(15, True, "Beacon")]
                assert required_player(session.combat_state, host).hp_current < 100
            await expect_round(call, session, host, {HOLLOW_A: [16]}, {HOLLOW_A: (16, True, None)})
    finally:
        await lifecycle.aclose()


async def beacon_scenario(world, scenario):
    await scenario(world)


SCENARIOS = {
    BEACON: (
        "patron_passives:orenthel_beacon",
        beacon_scenario,
        [(independent_attackers,), (protected_pair,), (prepared_and_held,)],
    ),
}
