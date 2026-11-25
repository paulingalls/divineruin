"""Smoke Bomb through authenticated combat tools and persisted encounters."""

import json
from collections.abc import AsyncIterator
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance._enemy_opportunity_helpers import declare as declare_all
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_entomb import favor
from acceptance.test_architect_fight import WORKS, pos
from acceptance.test_architect_fight import enter as enter_architect
from acceptance.test_iron_stance import ability, attack
from acceptance.test_martial_core_kit import enter, weapon_attack
from acceptance.test_opportunity_strike import participant, reconnect
from acceptance.test_self_buff_electives import bandit_attack, declare, defend, discovered, equip, receipt
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory

import character_spells
import combat_spatial
import conditions
import db_queries

SMOKE = "rogue_smoke_bomb"


@pytest.fixture
async def smoke_walk(reset_db_pool: str, request: pytest.FixtureRequest) -> AsyncIterator[MawlingHarness]:
    walk = MawlingHarness()
    try:
        encounter, location = getattr(request, "param", ("bandit_ambush", "greyvale_wilderness_north"))
        await walk.prepare((8, 8), companion=None, location=location)
        walk.encounter_id = encounter
        await walk.pool.execute(
            """UPDATE players SET data = data || '{"class":"rogue"}' WHERE player_id=$1""", walk.players[0]
        )
        await equip(walk, SMOKE)
        yield walk
    finally:
        await walk.close()


async def test_throw_and_reload(smoke_walk: MawlingHarness) -> None:
    walk = smoke_walk
    await enter(walk)
    rogue, ally = walk.players
    state = await walk.reload()
    combat_spatial.place(state, rogue, pos(0))
    await walk.persist()
    assert (await discovered(walk, SMOKE))["id"] == SMOKE
    instructions = walk.session.current_agent.instructions
    before = await db_queries.get_player(rogue)
    assert before is not None
    await declare(walk, ability(rogue, SMOKE), defend(ally))
    result = await walk.command("resolve_phase", {})
    thrown = receipt(result["packets"], rogue)
    assert thrown["resolved"] and thrown["deducted"] == {"focus": 0, "stamina": 3}
    await walk.reload()
    facts = await walk.command("query_info", {"kind": "combat"})
    cloud = facts["zones"][thrown["zone_id"]]
    assert cloud["kind"] == "smoke" and cloud["radius_ft"] == 10
    assert cloud["center"] == facts["locations"][cloud["center_id"]] == pos(0)
    assert rogue in cloud["members"]
    assert cloud["name"] == "Smoke cloud"
    rogue_name = participant(state, rogue).name
    assert any(line.startswith("Smoke cloud") and "10 feet" in line and rogue_name in line for line in facts["spoken"])
    after = await db_queries.get_player(rogue)
    assert after is not None
    assert after["stamina"]["current"] == before["stamina"]["current"] - 3
    assert after["focus"] == before["focus"]
    assert isinstance(instructions, str)
    assert 'Smoke Bomb (action="rogue_smoke_bomb") uses empty targets or targets the rogue.' in instructions
    assert "The smoke cloud stays at the throw point until the next round starts." in instructions


@pytest.mark.parametrize("smoke_walk", [("hollow_architect", WORKS)], indirect=True)
async def test_construct_slam_leaves_cloud_at_throw_point_until_wrap(smoke_walk: MawlingHarness) -> None:
    walk = smoke_walk
    entered = await enter_architect(walk)
    rogue, ally = walk.players
    assert entered.architect_encounter is not None
    foe = entered.architect_encounter["owner_id"]
    await declare(walk, ability(foe, "Summon Constructs"))
    with patch("architect_constructs.roll", return_value=_damage_die(2)):
        await walk.drain()
    state = await walk.reload()
    assert state.architect_encounter is not None
    construct = state.architect_encounter["construct_ids"][0]
    defender = participant(state, rogue)
    defender.reaction_ids = ["cleric_shield_of_faith"]
    defender.has_reaction_ability = True
    combat_spatial.place(state, construct, pos(24))
    combat_spatial.place(state, foe, pos(0))
    combat_spatial.place(state, rogue, pos(5))
    spatial = combat_spatial.require_spatial(state)
    spatial["locations"]["landmark"] = pos(-50)
    spatial["zones"]["landmark_silence"] = {"kind": "silence", "center_id": "landmark", "radius_ft": 10}
    await walk.persist()

    await declare(
        walk,
        ability(rogue, SMOKE, rogue),
        defend(ally),
        attack(foe, rogue, "Construct Slam"),
        attack(construct, rogue, "Slam"),
    )
    cloud_id = receipt((await walk.command("resolve_phase", {}))["packets"], rogue)["zone_id"]
    await reconnect(walk)
    with (
        patch("check_resolution.dice_roll", return_value=_d20(19)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        for _ in range(5):
            enemies = await walk.command("resolve_phase", {})
            if any(packet["actor_id"] == foe for packet in enemies["packets"]):
                break
        else:
            pytest.fail(f"Construct Slam did not resolve: {enemies}")
    assert receipt(enemies["packets"], foe)["push"]["destination"] == pos(20)
    await walk.reload()
    facts = await walk.command("query_info", {"kind": "combat"})
    cloud = facts["zones"][cloud_id]
    assert cloud["center"] == pos(5)
    assert facts["positions"][rogue] == pos(20) and rogue not in cloud["members"]
    assert facts["locations"][cloud["center_id"]] == pos(5)
    before_wrap = await walk.reload()
    assert before_wrap.round_number == state.round_number
    assert before_wrap.open_window is not None
    assert before_wrap.held_actions[0]["actor_id"] == construct
    with (
        patch("check_resolution.dice_roll", return_value=_d20(1)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        await walk.drain()
    next_round = await walk.reload()
    assert next_round.round_number == before_wrap.round_number + 1
    facts = await walk.command("query_info", {"kind": "combat"})
    assert cloud_id not in facts["zones"] and cloud["center_id"] not in facts["locations"]
    assert not any(line.startswith("Smoke cloud") for line in facts["spoken"])
    assert facts["positions"][rogue] == pos(20)
    assert facts["locations"]["landmark"] == pos(-50)
    assert facts["zones"]["landmark_silence"]["kind"] == "silence"


@pytest.mark.parametrize(
    "mode,draws,face",
    [("enemy", 2, 15), ("warrior", 2, 15), ("prone", 1, 19), ("outside", 1, 19)],
)
async def test_smoke_weapon_rolls(smoke_walk: MawlingHarness, mode: str, draws: int, face: int) -> None:
    walk = smoke_walk
    rogue, warrior = walk.players
    if mode == "outside":
        player = await db_queries.get_player(warrior)
        assert player is not None
        player["equipment"]["main_hand"].update(name="Shortbow", ranged=True, reach=80, damage_type="piercing")
        await walk.pool.execute("UPDATE players SET data=$2::jsonb WHERE player_id=$1", warrior, json.dumps(player))
    await enter(walk)
    state = await walk.reload()
    foe = next(p for p in state.participants if p.creature_id == "bandit")
    foe.hp_current = foe.hp_max = 100
    participant(state, rogue).initiative = 30
    combat_spatial.place(state, rogue, pos(0))
    combat_spatial.place(state, warrior, pos(15))
    combat_spatial.place(state, foe.id, pos(-15 if mode == "outside" else 10))
    spatial = combat_spatial.require_spatial(state)
    spatial["zones"]["ordinary_aura"] = {"center_id": warrior, "radius_ft": 0}
    if mode == "prone":
        foe.conditions = conditions.apply_condition(foe.conditions, "prone", duration=2, source=rogue)
    if mode == "warrior":
        spatial["locations"]["future_origin"] = pos(-70)
        spatial["zones"]["future_cloud"] = {
            "kind": "smoke",
            "center_id": "future_origin",
            "radius_ft": 10,
            "expires_round": state.round_number + 2,
        }
    await walk.persist()
    walk.enemies = [p.id for p in state.participants if p.type == "enemy"]
    swing = await bandit_attack(walk, foe.id, warrior) if mode == "enemy" else weapon_attack(warrior, foe.id, "")
    if mode == "outside":
        swing["action"] = "Shortbow"
    await declare_all(walk, ability(rogue, SMOKE), swing)
    with (
        patch("check_resolution.dice_roll", side_effect=map(_d20, [19, 15])) as rolls,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        first = await walk.command("resolve_phase", {})
        assert receipt(first["packets"], rogue)["resolved"]
        cloud = combat_spatial.require_spatial(await walk.reload())["zones"]
        assert any(zone.get("kind") == "smoke" for zone in cloud.values())
        packets = [*first["packets"], *(await walk.drain())]
    assert receipt(packets, swing["actor_id"])["roll"] == face
    assert rolls.call_count == draws
    if mode == "warrior":
        next_spatial = combat_spatial.require_spatial(await walk.reload())
        assert next_spatial["zones"]["future_cloud"]["expires_round"] == state.round_number + 2
        assert next_spatial["locations"]["future_origin"] == pos(-70)
        await declare_all(walk, swing)
        with (
            patch("check_resolution.dice_roll", return_value=_d20(19)) as next_roll,
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
        ):
            ordinary = receipt(await walk.drain(), warrior)
        next_roll.assert_called_once()
        assert ordinary["roll"] == 19


async def test_held_spell_keeps_smoke_roll_after_reconnect(smoke_walk: MawlingHarness) -> None:
    walk = smoke_walk
    rogue, mage = walk.players
    await walk.pool.execute("""UPDATE players SET data = data || '{"class":"mage"}' WHERE player_id=$1""", mage)
    await character_spells.record_learned(mage, "arcane_bolt", "discovery", is_prepared=True, conn=walk.pool)
    await favor(walk)
    await enter(walk)
    state = await walk.reload()
    participant(state, rogue).initiative = 30
    foe = next(p for p in state.participants if p.creature_id == "bandit")
    foe.hp_current = foe.hp_max = 100
    combat_spatial.place(state, rogue, pos(0))
    combat_spatial.place(state, mage, pos(15))
    combat_spatial.place(state, foe.id, pos(10))
    await walk.persist()
    walk.enemies = [p.id for p in state.participants if p.type == "enemy"]
    await declare_all(walk, ability(rogue, SMOKE), ability(mage, "arcane_bolt", foe.id))
    with (
        patch("check_resolution.dice_roll", side_effect=map(_d20, [19, 15])) as rolls,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)) as damage,
    ):
        first = await walk.command("resolve_phase", {})
        cloud_id = receipt(first["packets"], rogue)["zone_id"]
        offer = first["fate_offer"]
        assert offer["roller_id"] == mage and offer["roll_kind"] == "attack" and offer["die"] == 15
        held = await walk.reload()
        assert participant(held, foe.id).hp_current == 100 and not damage.called
        assert held.ally_continuation is not None
        prepared = held.ally_continuation["steps"]["spell_damage"]["prepared"]
        assert prepared["d20"]["disadvantage"] is True and prepared["d20"]["advantage"] is False
        await reconnect(walk)
        result = await walk.command("resolve_phase", {})
    packets = result["packets"] + result.get("settled_fate", {}).get("packets", [])
    landed = receipt(packets, mage)["cast"]["damage_result"]
    assert landed["roll"] == offer["die"] and landed["hit"]
    damage.assert_called_once()
    assert rolls.call_count == 2
    assert participant(await walk.reload(), foe.id).hp_current == 100 - landed["damage"] < 100
    assert cloud_id in (await walk.command("query_info", {"kind": "combat"}))["zones"]
