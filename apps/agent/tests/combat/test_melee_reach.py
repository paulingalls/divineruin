"""Melee approaches through voice commands, persisted placement and actual rolls."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from acceptance.mawling_harness import MawlingHarness

from combat_spatial import distance


@pytest.fixture
def mock_combat_agent_factory():
    return None


@pytest.fixture
async def maw(dev_db_pool, request):
    harness = MawlingHarness()
    try:
        await harness.start(gear=True, companion=True, reactions=getattr(request, "param", False))
        yield harness
    finally:
        await harness.close()


async def attack(maw, actor_id, target_id, action):
    state = maw.sd.combat_state
    result = await maw.command(
        "declare_phase",
        {
            "declarations": [
                {
                    "kind": "attack",
                    "actor_id": actor_id,
                    "action": action,
                    "target_id": target_id,
                    "held_item_id": "shortsword_basic"
                    if actor_id in maw.enemies and action == "Dissolution Maw"
                    else "",
                    "rider": "",
                },
                *[
                    {"kind": "defend", "actor_id": p.id}
                    for p in state.participants
                    if p.id != actor_id and not p.is_fallen
                ],
            ]
        },
    )
    assert result, result
    return await maw.drain()


@pytest.mark.parametrize("identity", ["primary", "party", "companion", "enemy"])
@pytest.mark.parametrize("separation", [25, 26.9, 50])
async def test_close_before_damage(maw, identity, separation):
    state = maw.sd.combat_state
    actor_id = {
        "primary": maw.players[0],
        "party": maw.players[1],
        "companion": "companion_kael",
        "enemy": maw.enemies[0],
    }[identity]
    target_id = maw.players[0] if identity == "enemy" else maw.enemies[0]
    actor, target = state.get_participant(actor_id), state.get_participant(target_id)
    action = next(
        a
        for a in actor.action_pool
        if a.get("damage") and not a.get("ranged") and (a["name"] == "Claw" if identity == "enemy" else True)
    )
    reach = action.get("reach", 5)
    actor.enhancers = []
    state.spatial["positions"][actor_id] = {"x": 0, "y": 0, "z": 0}
    state.spatial["positions"][target_id] = {"x": separation, "y": 0, "z": 0}
    state.spatial["speeds"][actor_id] = 30
    hp = target.hp_current
    await maw.persist()
    from combat_attack_roll import roll_attack

    def roll(*args, **kwargs):
        live = kwargs["combat_state"]
        assert distance(live.spatial["positions"][actor_id], live.spatial["positions"][target_id]) <= reach + 0.00000001
        return roll_attack(*args, **kwargs)

    with (
        patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=15)),
        patch("check_resolution_attack.dice_roll", return_value=SimpleNamespace(total=4)),
        patch("combat_support.roll_attack", side_effect=roll) as allied,
        patch("combat_hold.roll_attack", side_effect=roll) as hostile,
    ):
        packets = await attack(maw, actor_id, target_id, action["name"])
    packet = next(p for p in reversed(packets) if p.get("actor_id") == actor_id)
    live = await maw.reload()
    assert live.spatial["positions"][actor_id]["x"] == pytest.approx(min(30, separation - reach))
    assert packet["closed_distance"]
    assert packet["moved_ft"] == pytest.approx(min(30, separation - reach))
    assert packet["destination"] == live.spatial["positions"][actor_id]
    assert packet["attack_resolved"] == (separation <= 35)
    assert hostile.call_count == (1 if identity == "enemy" and separation <= 35 else 0)
    assert allied.call_count == (1 if separation <= 35 else 0)
    assert live.get_participant(target_id).hp_current == hp - packet.get("damage", 0)
    if separation <= 35:
        assert packet["hit"] and packet["damage"] > 0
    else:
        assert "reach" in packet["reason"]
        assert not live.first_attack_resolved
        assert not maw.sd.party.member(maw.players[0]).weapon_used


@pytest.mark.parametrize(
    "mode,separation,reach,expected",
    [
        ("plain", 3, 5, 0),
        ("plain", 35, 5, 30),
        ("plain", 35.01, 5, 30),
        ("numeric", 40, 10, 30),
        ("property", 40, 10, 30),
        ("numeric", 45, 15, 30),
        ("diagonal", 1227**0.5, 5, 30),
        ("grappled", 25, 5, 0),
        ("restrained", 25, 5, 0),
        ("zero", 25, 5, 0),
        ("choir", 25, 5, 0),
        ("grappled", 3, 5, 0),
        ("boolean", 50, 5, 0),
        ("ranged_property", 50, 5, 0),
        ("ranged_type", 50, 5, 0),
        ("extra", 50, 5, 30),
        ("bash", 40, 10, 30),
    ],
)
async def test_geometry_and_allowance(maw, mode, separation, reach, expected):
    state = maw.sd.combat_state
    actor, target = state.get_participant(maw.players[0]), state.get_participant(maw.enemies[0])
    action = next(a for a in actor.action_pool if a.get("damage"))
    action.pop("reach", None)
    actor.enhancers = []
    if mode in ("numeric", "bash"):
        action["reach"] = reach
    if mode == "property":
        action["properties"] = ["reach"]
    if mode == "boolean":
        action["ranged"] = True
    if mode == "ranged_property":
        action["properties"] = ["ranged"]
    if mode == "ranged_type":
        action["type"] = "ranged"
    if mode in ("grappled", "restrained"):
        actor.conditions = [{"type": mode, "source": target.id, "duration": None}]
    if mode == "choir":
        actor.choir_movement_round = state.round_number
    if mode in ("extra", "bash"):
        actor.enhancers = ["extra_attack" if mode == "extra" else "shield_bash"]
    state.spatial["speeds"][actor.id] = 0 if mode == "zero" else 30
    origin = {"x": 0, "y": 0, "z": 0}
    state.spatial["positions"][actor.id] = origin
    state.spatial["positions"][target.id] = (
        {"x": 1, "y": 1, "z": 35} if mode == "diagonal" else {"x": separation, "y": 0, "z": 0}
    )
    await maw.persist()
    with (
        patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=15)) as rolls,
        patch("check_resolution_attack.dice_roll", return_value=SimpleNamespace(total=4)),
    ):
        packets = await attack(maw, actor.id, target.id, action["name"])
    packet = next(p for p in reversed(packets) if p.get("actor_id") == actor.id)
    live = await maw.reload()
    assert distance(origin, live.spatial["positions"][actor.id]) == pytest.approx(expected)
    ranged = mode in ("boolean", "ranged_property", "ranged_type")
    can_hit = ranged or separation - expected <= reach
    assert rolls.call_count == int(can_hit)
    if not ranged:
        assert packet["attack_resolved"] == can_hit
    if not can_hit:
        assert packet["reason"]
        assert not live.first_attack_resolved
    if mode == "bash":
        assert packet["attacks"][1]["attack_resolved"] is False
        assert packet["attacks"][1]["moved_ft"] == 0


@pytest.mark.parametrize("maw", [True], indirect=True)
async def test_composite_shares_speed_across_reload(maw):
    state = maw.sd.combat_state
    actor = state.get_participant(maw.enemies[0])
    state.spatial["positions"][actor.id] = {"x": 0, "y": 0, "z": 0}
    state.spatial["speeds"][actor.id] = 30
    for pid, x in zip(maw.players, (20, 80), strict=True):
        state.spatial["positions"][pid] = {"x": x, "y": 0, "z": 0}
    await maw.persist()
    declaration = maw.composite(maw.players)
    declaration["strikes"][1]["held_item_id"] = "shortsword_basic"
    with (
        patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=15)) as rolls,
        patch("check_resolution_attack.dice_roll", return_value=SimpleNamespace(total=4)),
    ):
        await maw.command("declare_phase", {"declarations": [declaration]})
        packets = await maw.drain()
    strikes = [p for p in packets if p.get("actor_id") == actor.id and not p.get("attack_pending")]
    assert len(strikes) == 2
    assert any(p.get("attack_pending") for p in packets)
    assert strikes[0]["attack_resolved"] and strikes[0]["moved_ft"] == 10
    assert not strikes[1]["attack_resolved"] and strikes[1]["moved_ft"] == 20
    assert rolls.call_count == 1
    live = await maw.reload()
    assert live.spatial["positions"][actor.id]["x"] == 30
    assert live.get_participant(maw.players[1]).hp_current == 100


@pytest.mark.parametrize("changed", ["stunned", "silence"])
async def test_resolution_checks_live_conditions_and_exposure(maw, changed):
    state = maw.sd.combat_state
    actor, target = state.get_participant(maw.players[0]), state.get_participant(maw.enemies[0])
    state.spatial["positions"][actor.id] = {"x": 0, "y": 0, "z": 0}
    state.spatial["positions"][target.id] = {"x": 25, "y": 0, "z": 0}
    actor.enhancers = []
    await maw.persist()
    await maw.command(
        "declare_phase",
        {
            "declarations": [
                {
                    "kind": "attack",
                    "actor_id": actor.id,
                    "action": actor.action_pool[0]["name"],
                    "target_id": target.id,
                    "held_item_id": "",
                    "rider": "",
                },
                *[{"kind": "defend", "actor_id": p.id} for p in state.participants if p.id != actor.id],
            ]
        },
    )
    state = maw.sd.combat_state
    if changed == "stunned":
        state.get_participant(actor.id).conditions = [{"type": "stunned", "duration": 3}]
    else:
        state.encounter_id = ""
        state.get_participant(target.id).creature_id = "hollow_choir"
        state.spatial["zones"]["silence"] = {"kind": "silence", "center_id": actor.id, "radius_ft": 10}
    await maw.persist()
    with (
        patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=15)) as rolls,
        patch("check_resolution_attack.dice_roll", return_value=SimpleNamespace(total=4)),
    ):
        packets = await maw.drain()
    packet = next(p for p in packets if p.get("actor_id") == actor.id)
    live = await maw.reload()
    if changed == "stunned":
        assert rolls.call_count == 0 and "stunned" in packet["reason"]
        assert live.spatial["positions"][actor.id]["x"] == 0
    else:
        assert packet["closed_distance"]
        assert live.get_participant(target.id).choir_silence_exposed
        assert live.get_participant(target.id).choir_suppression["active"]


@pytest.mark.parametrize("maw", [True], indirect=True)
async def test_interrupted_charge_keeps_movement_receipt(maw):
    state = maw.sd.combat_state
    actor, target = state.get_participant(maw.enemies[0]), state.get_participant(maw.players[0])
    state.spatial["positions"][actor.id] = {"x": 0, "y": 0, "z": 0}
    state.spatial["positions"][target.id] = {"x": 25, "y": 0, "z": 0}
    await maw.persist()
    await maw.command(
        "declare_phase",
        {
            "declarations": [
                {
                    "kind": "attack",
                    "actor_id": actor.id,
                    "action": "Claw",
                    "target_id": target.id,
                    "held_item_id": "",
                    "rider": "",
                },
                *[{"kind": "defend", "actor_id": p.id} for p in state.participants if p.id != actor.id],
            ]
        },
    )
    with patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=15)):
        for _ in range(4):
            paused = await maw.command("resolve_phase", {})
            if maw.sd.combat_state.open_window is not None:
                break
    assert any(p.get("closed_distance") for p in paused["packets"])
    live = await maw.reload()
    assert live.open_window is not None
    hp = live.get_participant(target.id).hp_current
    live.get_participant(actor.id).conditions = [{"type": "stunned", "duration": 3}]
    await maw.persist()
    packets = await maw.drain()
    packet = next(p for p in packets if p.get("actor_id") == actor.id)
    assert not packet["resolved"] and "stunned" in packet["reason"]
    assert packet["closed_distance"] and not packet["attack_resolved"]
    assert packet["moved_ft"] == 15
    assert packet["destination"] == maw.sd.combat_state.spatial["positions"][actor.id]
    assert maw.sd.combat_state.get_participant(target.id).hp_current == hp
