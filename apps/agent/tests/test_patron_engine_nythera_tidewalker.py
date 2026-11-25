"""Tidewalker through registered combat declarations and saved combat state."""

from collections.abc import Awaitable, Callable
from types import SimpleNamespace

import pytest
from _mortaen_threshold_fixtures import active, checkpoint, drain, fight, reload_state, rolls
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack
from acceptance.test_architect_fight import pos
from acceptance.test_retreat import retreat
from livekit.agents.llm import ToolError
from test_patron_engine_thyra_thornwall import declare, move
from voice_condition_fixtures import spatial_record

GIFT = "nythera_tidewalker"
MUD = "bandit_ambush"
WATER = "hollow_mawling_pack"
DOMAIN = "hollow_architect"
FOE = "bandit_1"
CROSSINGS = {
    MUD: (pos(20, -15, 10), "mud"),
    WATER: (pos(15, -10), "water"),
    DOMAIN: (pos(0), "architect_domain"),
}


def place(world: SimpleNamespace, actor: str, origin: dict, *, speed: int = 20, foe: dict | None = None) -> dict:
    state = active(world)
    spatial = spatial_record(state)
    for index, other in enumerate(p for p in state.participants if p.id != actor and not p.is_structure):
        spatial["positions"][other.id] = pos(-30, 30 + 5 * index)
    spatial["positions"][actor] = origin
    spatial["speeds"][actor] = speed
    if foe is not None:
        spatial["positions"][FOE] = foe
    return spatial["movement_areas"]


def area(kind: str) -> dict:
    return {
        "shape": "rectangle",
        "kind": kind,
        "min": pos(-5, -5),
        "max": pos(35, 5),
        "excluded_actor_ids": [],
    }


def movement(packets: list[dict], actor: str) -> dict:
    (packet,) = (p for p in packets if p["actor_id"] == actor and "moved_ft" in p)
    return packet


async def assert_travel(
    world: SimpleNamespace, packet: dict, actor: str, endpoint: dict, travelled: int, spent: int
) -> None:
    assert packet["destination"] == pytest.approx(endpoint)
    assert packet["moved_ft"] == pytest.approx(travelled)
    assert packet["movement_spent_ft"] == pytest.approx(spent)
    assert spatial_record(await reload_state(world))["positions"][actor] == pytest.approx(endpoint)


async def crossing(world: SimpleNamespace, encounter: str, patron: str, guest: str, index: int, spent: int) -> None:
    async with fight(
        world, patron=patron, guest=guest, favor=0, guest_favor=0, gifts={}, encounter_id=encounter
    ) as call:
        actor = world.ids[index]
        origin, kind = CROSSINGS[encounter]
        endpoint = {**origin, "x": origin["x"] + 10}
        areas = place(world, actor, origin)
        assert {area["kind"] for area in areas.values()} == {kind}
        await checkpoint(world)
        await declare(world, call, {**move(actor, endpoint["x"]), "destination": endpoint})
        packets, _ = await drain(world, call)
        packet = movement(packets, actor)
        assert packet["resolved"]
        await assert_travel(world, packet, actor, endpoint, 10, spent)


async def approach(world: SimpleNamespace) -> None:
    async with fight(world, patron="nythera", favor=0, gifts={}, encounter_id=MUD) as call:
        actor = world.ids[0]
        areas = place(world, actor, pos(0), speed=10, foe=pos(30))
        areas["route_mud"] = area("mud")
        await checkpoint(world)
        await declare(world, call, attack(actor, FOE))
        packets, _ = await drain(world, call)
        packet = movement(packets, actor)
        assert not packet["attack_resolved"]
        await assert_travel(world, packet, actor, pos(10), 10, 10)


async def resumed_move(world: SimpleNamespace) -> None:
    async with fight(world, patron="nythera", favor=0, gifts={}, encounter_id=MUD, guest_class="cleric") as call:
        actor, ally = world.ids
        areas = place(world, actor, pos(3), speed=10, foe=pos(0))
        spatial_record(active(world))["positions"][ally] = pos(-20)
        areas["route_mud"] = area("mud")
        await checkpoint(world)
        await declare(world, call, move(actor, 13))
        with rolls(1):
            first = await call("resolve_phase")
            waiting = first["next"]["waiting_on"]
            assert waiting["stage"] == "pre_roll"
            assert (ally, "cleric_shield_of_faith") in {(r["actor_id"], r["id"]) for r in waiting["reactions"]}
            paused = await reload_state(world)
            assert spatial_record(paused)["positions"][actor] == pos(5)
            assert paused.ally_continuation is not None
            route = paused.ally_continuation["steps"]["movement_route"]
            assert route["endpoint"] == pos(13)
            assert route["facts"]["movement_spent_ft"] == 2
            assert route["budget"]["remaining"] == 8
            assert route["execution_id"] == paused.held_actions[0]["execution_id"]
            packets, _ = await drain(world, call)
        packets = first["packets"] + packets
        (strike,) = (p for p in packets if p.get("opportunity_attack"))
        assert (strike["actor_id"], strike["target_id"], strike["hit"]) == (FOE, actor, False)
        packet = movement(packets, actor)
        assert packet["resolved"]
        await assert_travel(world, packet, actor, pos(13), 10, 10)


async def withdrawal(world: SimpleNamespace) -> None:
    async with fight(world, patron="nythera", favor=0, gifts={}, encounter_id=MUD) as call:
        actor = world.ids[0]
        areas = place(world, actor, pos(10), speed=10, foe=pos(0))
        state = active(world)
        positions = spatial_record(state)["positions"]
        for enemy in state.participants:
            if enemy.type == "enemy":
                positions[enemy.id]["y"] = 0
        areas["route_mud"] = area("mud")
        await checkpoint(world)
        await declare(world, call, retreat(actor))
        packets, _ = await drain(world, call)
        packet = movement(packets, actor)
        assert packet["resolved"] and packet["declaration_type"] == "retreat"
        await assert_travel(world, packet, actor, pos(20), 10, 10)


async def other_ground(world: SimpleNamespace, kind: str) -> None:
    async with fight(world, patron="nythera", favor=0, gifts={}, encounter_id=MUD) as call:
        actor = world.ids[0]
        areas = place(world, actor, pos(20, -15, 10))
        mud = areas["muddy_slope"]
        areas[kind] = {**mud, "kind": kind}
        await checkpoint(world)
        action = move(actor, 30, -15)
        action["destination"] = pos(30, -15, 10)
        if kind == "low_ceiling":
            with pytest.raises(ToolError, match="cannot fly through a lowered ceiling"):
                await declare(world, call, {**action, "movement_mode": "flying"})
            assert spatial_record(await reload_state(world))["positions"][actor] == pos(20, -15, 10)
        await declare(world, call, action)
        packets, _ = await drain(world, call)
        packet = movement(packets, actor)
        assert packet["resolved"]
        await assert_travel(world, packet, actor, pos(30, -15, 10), 10, 20)


async def discovery(world: SimpleNamespace) -> None:
    async with fight(world, patron="nythera", favor=0, gifts={}) as call:
        gift = next(g for g in (await call("query_info", kind="patron"))["abilities"] if g["id"] == GIFT)
        hint = gift.get("activation_hint", "").lower()
        assert all(word in hint for word in ("automatically", "water", "mud", "shifting ground", "low ceilings"))
        assert (gift["tier"], gift["status"], gift["recharge"], gift["eligible"], gift["available"]) == (
            "Acknowledged",
            "active",
            "always",
            True,
            False,
        )


async def scenario(world: SimpleNamespace, check: Callable[..., Awaitable[None]], *args: object) -> None:
    await check(world, *args)


CASES = [
    (crossing, encounter, patron, "aelora", 0, spent)
    for encounter in CROSSINGS
    for patron, spent in (("nythera", 10), ("none", 20), ("aelora", 20))
] + [
    (crossing, MUD, "none", "nythera", 1, 10),
    (crossing, MUD, "nythera", "none", 1, 20),
    (approach,),
    (resumed_move,),
    (withdrawal,),
    (other_ground, "low_ceiling"),
    (other_ground, "rubble"),
    (discovery,),
]
SCENARIOS = {GIFT: ("patron_passives:tidewalker", scenario, CASES)}
