"""Iron Stance through the registered combat tools and persisted encounter."""

import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_fight import WORKS, pos
from acceptance.test_architect_fight import enter as enter_architect
from acceptance.test_martial_core_kit import enter, weapon_attack
from acceptance.test_opportunity_strike import participant
from acceptance.test_retreat import retreat
from acceptance.test_self_buff_electives import condition_types, defend, discovered, equip, receipt, stamina
from acceptance.test_still_anchors import enter as enter_still
from acceptance.test_still_anchors import fresh_session, search_round, strike
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory

import ability_persistence
import combat_spatial
import conditions
import event_types
from combat_structures import add_wall

STANCE = "warrior_iron_stance"


@pytest.fixture
async def walk(reset_db_pool: str, request: pytest.FixtureRequest):
    harness = MawlingHarness()
    try:
        encounter, location = getattr(request, "param", ("bandit_ambush", "greyvale_wilderness_north"))
        await harness.prepare((8, 8), companion=None, location=location)
        harness.encounter_id = encounter
        await equip(harness, STANCE)
        yield harness
    finally:
        await harness.close()


def stance(actor: str, *targets: str) -> dict:
    return {
        "kind": "ability",
        "actor_id": actor,
        "action": STANCE,
        "reshape": [],
        "targets": list(targets),
        "argument_type": "",
    }


@pytest.mark.parametrize("explicit_self", [False, True])
async def test_declare_iron_stance(walk: MawlingHarness, explicit_self: bool) -> None:
    await enter(walk)
    actor, ally = walk.players
    assert (await discovered(walk, STANCE))["id"] == STANCE
    instructions = walk.session.current_agent.instructions
    assert isinstance(instructions, str)
    assert 'Iron Stance (action="warrior_iron_stance") uses empty targets.' in instructions
    assert (
        "Until the warrior's next turn, forced movement fails, saves have advantage, and all damage is resisted."
        in instructions
    )
    before = await stamina(actor)
    action = stance(actor, *([actor] if explicit_self else []))
    await walk.command("declare_phase", {"declarations": [action, defend(ally)]})
    assert receipt(await walk.drain(), actor)["condition_applied"] == "iron_stance"
    assert await stamina(actor) == before - 3
    assert "iron_stance" in await condition_types(walk, actor)
    assert "iron_stance" not in await condition_types(walk, ally)
    room = walk.sd.room
    assert room is not None
    publish = room.local_participant.publish_data
    assert isinstance(publish, AsyncMock)
    events = [json.loads(call.args[0]) for call in publish.call_args_list]
    assert any(
        condition["type"] == "iron_stance"
        for event in events
        if event["type"] == event_types.COMBAT_UI_UPDATE
        for combatant in event["combatants"]
        if combatant["id"] == actor
        for condition in combatant["conditions"]
    )


async def declare(walk: MawlingHarness, *actions: dict, error: bool = False):
    return await walk.command("declare_phase", {"declarations": list(actions)}, error=error)


def attack(actor: str, target: str, action: str) -> dict:
    return {**weapon_attack(actor, target, ""), "action": action}


def ability(actor: str, action: str, *targets: str) -> dict:
    return {**stance(actor, *targets), "action": action}


@pytest.mark.parametrize("refusal", ["ally", "foe", "many", "unowned", "stamina"])
async def test_refused_stance_leaves_state_unchanged(walk: MawlingHarness, refusal: str) -> None:
    actor, ally = walk.players
    if refusal == "unowned":
        await walk.pool.execute("DELETE FROM character_abilities WHERE player_id=$1 AND ability_id=$2", actor, STANCE)
    if refusal == "stamina":
        await ability_persistence.update_player_resources(actor, stamina=2, conn=walk.pool)
    await enter(walk)
    foe = next(p.id for p in (await walk.reload()).participants if not p.is_ally)
    targets = {"ally": [ally], "foe": [foe], "many": [actor, ally]}.get(refusal, [])
    before = await walk.snapshot()
    if refusal in {"unowned", "stamina"}:
        await declare(walk, stance(actor))
        refusal_message = await walk.command("resolve_phase", {}, error=True)
        assert ("stamina" if refusal == "stamina" else "learned") in refusal_message.lower()
        assert (await walk.snapshot())[1] == before[1]
        assert "iron_stance" not in await condition_types(walk, actor)
    else:
        assert "only protects" in await declare(walk, stance(actor, *targets), error=True)
        assert await walk.snapshot() == before


async def place_foe(walk: MawlingHarness, species: str) -> str:
    state = await walk.reload()
    foe = next(p for p in state.participants if p.creature_id == species)
    combat_spatial.place(state, walk.players[0], pos(3))
    combat_spatial.place(state, foe.id, pos(0))
    await walk.persist()
    return foe.id


@pytest.mark.parametrize("next_action", ["move", "retreat", "defend"])
async def test_stance_survives_until_own_packet(walk: MawlingHarness, next_action: str) -> None:
    await enter(walk)
    actor, ally = walk.players
    foe = await place_foe(walk, "bandit_captain")
    blow = attack(foe, actor, "Longsword")
    await declare(walk, stance(actor), defend(ally), blow)
    with (
        patch("check_resolution.dice_roll", return_value=_d20(19)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(9)),
    ):
        result = receipt(await walk.drain(), foe)
    assert (result["damage_type"], result["damage"]) == ("slashing", 5)
    assert participant(await walk.reload(), actor).hp_current == 95
    await fresh_session(walk, await walk.reload())
    before = await stamina(actor)
    assert "iron_stance" in await condition_types(walk, actor)

    move = {"kind": "move", "actor_id": actor, "reshape": [], "destination": pos(4), "movement_mode": "ground"}
    if next_action == "move":
        snapshot = await walk.snapshot()
        await declare(walk, {**move, "destination": pos(400)}, error=True)
        assert await walk.snapshot() == snapshot
    action = {"defend": defend(actor), "move": move, "retreat": retreat(actor)}[next_action]
    await declare(walk, action, *([blow] if next_action == "defend" else []))
    assert "iron_stance" in await condition_types(walk, actor)
    with (
        patch("check_resolution.dice_roll", return_value=_d20(19)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(9)),
    ):
        packets = await walk.drain()
    result = receipt(packets, actor)
    assert result["resolved"]
    assert "iron_stance" not in await condition_types(walk, actor)
    if next_action == "defend":
        assert result["ac_bonus"] == 2
        assert receipt(packets, foe)["damage"] == 11
    else:
        assert result["moved_ft"] == (1 if next_action == "move" else 30)
    assert await stamina(actor) == before


@pytest.mark.parametrize(("stanced", "faces"), [(False, [1]), (True, [1, 20]), (True, [20, 1])])
@pytest.mark.parametrize("walk", [("fragment_shadeling", "greyvale_wilderness_north")], indirect=True)
async def test_necrotic_hit_and_death_save(walk: MawlingHarness, stanced: bool, faces: list[int]) -> None:
    await enter(walk)
    actor = walk.players[0]
    foe = await place_foe(walk, "hollow_shadeling")
    state = await walk.reload()
    participant(state, actor).hp_current = 4
    await walk.persist()
    await declare(walk, stance(actor) if stanced else defend(actor), attack(foe, actor, "Corrosive Touch"))
    with (
        patch("check_resolution.dice_roll", return_value=_d20(19)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(9)),
    ):
        result = receipt(await walk.drain(), foe)
    assert (result["damage_type"], result["damage"]) == ("necrotic", 4 if stanced else 9)
    assert participant(await walk.reload(), actor).is_fallen
    with patch("combat_resolution.dice_roll", side_effect=map(_d20, faces)) as rolls:
        saved = await walk.command("request_death_save", {"player_id": actor})
    assert rolls.call_count == (2 if stanced else 1)
    assert saved["roll"] == (20 if stanced else 1)
    after = participant(await walk.reload(), actor)
    assert (after.hp_current, after.death_save_failures) == ((1, 0) if stanced else (0, 2))


@pytest.mark.parametrize("walk", [("hollow_architect", WORKS)], indirect=True)
async def test_slam_cannot_move_reloaded_warrior(walk: MawlingHarness) -> None:
    state = await enter_architect(walk)
    actor = walk.players[0]
    assert state.architect_encounter is not None
    foe = state.architect_encounter["owner_id"]
    combat_spatial.place(state, foe, pos(0))
    combat_spatial.place(state, actor, pos(5))
    add_wall(state, "wall", "Wall", pos(10, -2), pos(10, 2))
    await walk.persist()
    await declare(walk, stance(actor), attack(foe, actor, "Construct Slam"))
    assert receipt((await walk.command("resolve_phase", {}))["packets"], actor)["condition_applied"] == "iron_stance"
    await fresh_session(walk, await walk.reload())
    with (
        patch("check_resolution.dice_roll", return_value=_d20(19)),
        patch("check_resolution_attack.dice_roll", side_effect=map(_damage_die, [7, 5])),
        patch("architect_actions.dice.roll", side_effect=AssertionError("blocked push rolled collision damage")),
    ):
        result = receipt(await walk.drain(), foe)
    assert result["push"] == {
        "distance_ft": 0,
        "destination": pos(5),
        "wall_id": None,
        "movement_blocked": "Iron Stance",
    }
    assert result["damage"] == 5
    state = await walk.reload()
    assert combat_spatial.require_spatial(state)["positions"][actor] == pos(5)
    assert participant(state, actor).hp_current == 95


@pytest.mark.parametrize("walk", [("hollow_still", "ashmark_still")], indirect=True)
async def test_still_ejection_cannot_move_stanced_warrior(walk: MawlingHarness) -> None:
    response, state = await enter_still(walk)
    actor = walk.players[0]
    assert state.still_encounter is not None
    owner = state.still_encounter["owner_id"]
    anchor = state.still_encounter["anchor_ids"][0]
    await search_round(walk, response["still"]["search_actions"][0])
    state = await walk.reload()
    start = combat_spatial.require_spatial(state)["positions"][anchor]
    combat_spatial.place(state, actor, start)
    await walk.persist()
    await declare(walk, {"actor_id": actor, **strike(anchor)})
    with (
        patch("check_resolution.dice_roll", return_value=_d20(1)),
        patch("combat_recharge.roll", return_value=_damage_die(6)),
    ):
        await walk.drain()
    still = (await walk.reload()).still_encounter
    assert still is not None and still["pending_rejection"]["anchor_id"] == anchor
    await declare(walk, stance(actor), ability(owner, "Rejection"))
    with patch("check_resolution.dice_roll", return_value=_d20(2)) as rolls:
        packets = await walk.drain()
    target = next(row for row in receipt(packets, owner)["targets"] if row["target_id"] == actor)
    assert rolls.call_count >= 2
    assert not target["save_success"]
    assert target["movement_blocked"] == "Iron Stance"
    assert combat_spatial.require_spatial(await walk.reload())["positions"][actor] == target["destination"] == start


@pytest.mark.parametrize("walk", [("cult_cell", "greyvale_wilderness_north")], indirect=True)
async def test_reloaded_stance_advantages_hostile_and_wrap_wisdom_saves(walk: MawlingHarness) -> None:
    await enter(walk)
    actor = walk.players[0]
    foe = await place_foe(walk, "cult_leader")
    state = await walk.reload()
    player = participant(state, actor)
    player.conditions = conditions.apply_condition(player.conditions, "frightened", source=foe)
    await walk.persist()
    await declare(walk, stance(actor), ability(foe, "Hold Person", actor))
    assert receipt((await walk.command("resolve_phase", {}))["packets"], actor)["condition_applied"] == "iron_stance"
    await fresh_session(walk, await walk.reload())
    with patch("check_resolution.dice_roll", side_effect=map(_d20, [2, 19, 3, 18])) as rolls:
        result = receipt(await walk.drain(), foe)
    assert rolls.call_count == 4
    assert result["save_type"] == "wisdom" and result["save_success"] and result["save_roll"] == 19
    assert await condition_types(walk, actor) == {"iron_stance"}


@pytest.mark.parametrize("walk", [("hollow_veilrender_boss", "greyvale_wilderness_north")], indirect=True)
async def test_damaging_save_lands_once(walk: MawlingHarness) -> None:
    await enter(walk)
    actor = walk.players[0]
    foe = await place_foe(walk, "hollow_veilrender")
    await declare(walk, stance(actor), ability(foe, "Corruption Wave", actor))
    with (
        patch("check_resolution.dice_roll", side_effect=map(_d20, [19, 19, 2, 2])),
        patch("combat_enemy_action.dice_roll", return_value=_damage_die(11)),
    ):
        packets = await walk.drain()
    wave = next(row for row in packets if row.get("action") == "Corruption Wave")
    target = next(row for row in wave["targets"] if row["target_id"] == actor)
    assert not target["save_success"]
    assert target["damage"] == 5
    assert participant(await walk.reload(), actor).hp_current == 95
    assert "poisoned" in await condition_types(walk, actor)

    await declare(walk, defend(actor))
    with (
        patch("check_resolution.dice_roll", return_value=_d20(2)) as rolls,
        patch("combat_veilrender.dice.roll", return_value=_damage_die(4)),
    ):
        start = receipt(await walk.drain(), actor)["turn_start_effects"][0]
    assert rolls.call_count == len(walk.players)
    assert start["source_id"] == foe and start["damage"] == 2
    assert "iron_stance" not in await condition_types(walk, actor)


@pytest.mark.parametrize("stance_used", [True, False])
@pytest.mark.parametrize("walk", [("hollow_choir", "greyvale_wilderness_north")], indirect=True)
async def test_choir_approach_runs_before_stance_expires(walk: MawlingHarness, stance_used: bool) -> None:
    await enter(walk)
    actor = walk.players[0]
    state = await walk.reload()
    foe = next(p.id for p in state.participants if p.creature_id == "hollow_choir")
    start = combat_spatial.require_spatial(state)["positions"][actor]
    await declare(walk, stance(actor) if stance_used else defend(actor), ability(foe, "Stolen Melody", actor))
    with patch("check_resolution.dice_roll", return_value=_d20(2)):
        await walk.drain()
    player = participant(await walk.reload(), actor)
    assert any(c["type"] == "charmed" and c.get("choir_melody") for c in player.conditions)
    await declare(walk, defend(actor))
    with patch("check_resolution.dice_roll", return_value=_d20(2)):
        packet = receipt(await walk.drain(), actor)
    state = await walk.reload()
    end = combat_spatial.require_spatial(state)["positions"][actor]
    assert packet["ac_bonus"] == 2
    if stance_used:
        assert end == start
        assert packet["turn_start_effects"] == [
            {
                "effect": "choir_approach",
                "actor_id": actor,
                "resolved": True,
                "forced_movement": True,
                "moved_ft": 0,
                "destination": start,
                "movement_blocked": "Iron Stance",
            }
        ]
    else:
        assert end != start
    assert "iron_stance" not in await condition_types(walk, actor)


async def test_petrified_resistance_does_not_stack_with_catalog_affinity(walk: MawlingHarness) -> None:
    actor, ally = walk.players
    walk.encounter_id = f"iron_stance_{uuid4().hex}"
    walk.owns_template = True
    template = {
        "id": walk.encounter_id,
        "recommended_party_level": 8,
        "enemies": [{"id": "treant", "creature_id": "corrupted_treant", "role": "standard"}],
        "scene_placement": {
            "party_start": pos(0),
            "companion_start": pos(0),
            "actors": {"treant": pos(3)},
            "locations": {},
            "zones": {},
        },
    }
    await walk.pool.execute(
        "INSERT INTO encounter_templates (id, data) VALUES ($1,$2::jsonb)", walk.encounter_id, json.dumps(template)
    )
    await walk.pool.execute(
        """UPDATE players SET data = jsonb_set(data, '{equipment,main_hand}',
           '{"name":"Spear","damage":"1d6","damage_type":"piercing"}') WHERE player_id = $1""",
        actor,
    )
    await enter(walk)
    state = await walk.reload()
    treant = participant(state, "treant")
    assert "piercing" in treant.damage_affinities["resistant"]
    treant.conditions = conditions.apply_condition(treant.conditions, "petrified")
    before = treant.hp_current
    await walk.persist()
    await declare(walk, attack(actor, "treant", "Spear"), attack(ally, "treant", "Longsword"))
    with (
        patch("check_resolution.dice_roll", return_value=_d20(19)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(10)),
    ):
        packets = await walk.drain()
    for wielder, damage_type in [(actor, "piercing"), (ally, "slashing")]:
        result = receipt(packets, wielder)
        assert (result["damage_type"], result["damage"]) == (damage_type, 5)
    assert participant(await walk.reload(), "treant").hp_current == before - 10
