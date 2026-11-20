"""Reactive Architecture through persisted combat commands."""

import json
from unittest.mock import patch

import pytest
from _zhael_fate_fixtures import attack, defend
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_fight import WORKS, declare_attack, enter, pos
from acceptance.test_architect_fight import isolated_content_cache as isolated_content_cache
from acceptance.test_architect_fight import mock_combat_agent_factory as mock_combat_agent_factory
from voice_condition_fixtures import participant

import combat_spatial
import db_queries
from combat_structures import blocks_path


@pytest.fixture
async def archers(reset_db_pool):
    harness = MawlingHarness()
    try:
        await harness.prepare((20, 20, 20), companion=None, location=WORKS)
        item = json.loads(await harness.pool.fetchval("SELECT data FROM items WHERE id='shortbow_common'"))
        for actor in harness.players:
            player = await db_queries.get_player(actor)
            assert player is not None
            player["equipment"]["main_hand"] = {
                "name": item["name"],
                "damage": item["damage_dice"],
                "damage_type": item["effects"][0]["damage_type"],
                "properties": [*item["properties"], item["subtype"]],
            }
            await harness.pool.execute(
                "UPDATE players SET data=$2::jsonb WHERE player_id=$1", actor, json.dumps(player)
            )
            await harness.pool.execute(
                "INSERT INTO player_inventory (player_id, item_id, data) VALUES ($1,'shortbow_common',$2::jsonb)",
                actor,
                json.dumps({"equipped": True, "current_hits": 25}),
            )
        state = await enter(harness)
        assert state.architect_encounter is not None
        owner_id = state.architect_encounter["owner_id"]
        participant(state, owner_id).ac = 23
        combat_spatial.place(state, owner_id, pos(-25, 25))
        for i, (actor, point) in enumerate(
            zip(harness.players, (pos(-45, 25), pos(-50, 25), pos(-25, 45)), strict=True)
        ):
            archer = participant(state, actor)
            archer.initiative = 30 - i
            archer.enhancers.clear()
            combat_spatial.place(state, actor, point)
        await harness.persist()
        yield harness
    finally:
        await harness.close()


def wall_raised(before, after, attacker):
    record = after.architect_encounter
    [wall_id] = set(record["structure_ids"]) - set(before.architect_encounter["structure_ids"])
    assert record["reaction_round"] == before.round_number
    wall = participant(after, wall_id)
    assert (wall.ac, wall.hp_max) == (19, 30)
    positions = before.spatial["positions"]
    if not wall.is_dead:
        assert blocks_path(positions[attacker], positions[record["owner_id"]], after.spatial["structures"][wall_id])
    return wall


def dice(face=20, damage=4):
    return (
        patch("check_resolution.dice_roll", return_value=_d20(face)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(damage)),
        patch("dice.roll", return_value=_damage_die(damage)),
    )


@pytest.mark.parametrize("case", ["hit", "miss", "extra_attack"])
async def test_first_arrow_strikes_wall(archers, case):
    actor = archers.players[0]
    state = await archers.reload()
    owner = state.architect_encounter["owner_id"]
    if case == "extra_attack":
        state.get_participant(actor).enhancers.append("extra_attack")
    before = await archers.persist()
    await declare_attack(archers, actor, owner, "Shortbow")
    d20, weapon, spell = dice(1 if case == "miss" else 20)
    with d20 as rolled, weapon, spell:
        [result] = [p for p in await archers.drain() if p["actor_id"] == actor]
    after = await archers.reload()
    wall = wall_raised(before, after, actor)
    assert after.get_participant(owner).hp_current == before.get_participant(owner).hp_current
    assert result["reactive_architecture"]["wall_id"] == wall.id
    assert result["target_id"] == wall.id and result["target_ac"] == 19
    assert 30 - wall.hp_current == result["damage"]
    assert result["hit"] is (case != "miss")
    assert rolled.call_count == 1
    if case == "extra_attack":
        first, second = result["attacks"]
        assert first["target_id"] == wall.id
        assert not second["resolved"] and wall.id in second["reason"] and "damage" not in second


async def test_later_shots_and_next_round(archers):
    first, crossing, clear = archers.players
    before = await archers.reload()
    owner = before.architect_encounter["owner_id"]
    await archers.command(
        "declare_phase",
        {"declarations": [bow(actor, owner) for actor in archers.players] + [defend(owner)]},
    )
    d20, weapon, spell = dice()
    with d20 as rolled, weapon, spell:
        results = {p["actor_id"]: p for p in await archers.drain()}
    after = await archers.reload()
    wall = wall_raised(before, after, first)
    assert results[first]["target_id"] == wall.id
    assert not results[crossing]["resolved"] and wall.id in results[crossing]["reason"]
    assert results[clear]["target_ac"] == 25 and results[clear]["damage"] > 0
    assert after.get_participant(owner).hp_current < before.get_participant(owner).hp_current
    assert rolled.call_count == 2

    await declare_attack(archers, clear, owner, "Shortbow")
    d20, weapon, spell = dice()
    with d20, weapon, spell:
        results = {p["actor_id"]: p for p in await archers.drain()}
    reloaded = await archers.reload()
    next_wall = wall_raised(after, reloaded, clear)
    assert next_wall.id != wall.id and results[clear]["target_id"] == next_wall.id
    assert reloaded.get_participant(owner).hp_current == after.get_participant(owner).hp_current


def bow(actor, target):
    return {**attack(actor, target), "action": "Shortbow"}


@pytest.mark.parametrize("case", ["other", "melee"])
async def test_other_attacks_do_not_spend_reaction(archers, case):
    actor, _, _ = archers.players
    state = await archers.reload()
    owner = state.architect_encounter["owner_id"]
    if case == "other":
        target = state.architect_encounter["structure_ids"][0]
        combat_spatial.place(state, actor, pos(25, 30))
        action = "Shortbow"
    else:
        target = owner
        combat_spatial.place(state, actor, pos(-28, 25))
        archer = state.get_participant(actor)
        archer.action_pool.append({"name": "Longsword", "damage": "1d8", "damage_type": "slashing"})
        action = "Longsword"
    before = await archers.persist()
    await declare_attack(archers, actor, target, action)
    d20, weapon, spell = dice()
    with d20, weapon, spell:
        [result] = [p for p in await archers.drain() if p["actor_id"] == actor]
    after = await archers.reload()
    assert result["damage"] > 0 and "reactive_architecture" not in result
    assert after.get_participant(target).hp_current < before.get_participant(target).hp_current
    assert after.architect_encounter == before.architect_encounter
