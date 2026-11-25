"""Taunt through equipped ability discovery, declarations, and round resolution."""

from collections.abc import AsyncIterator
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_fight import WORKS, pos
from acceptance.test_architect_fight import enter as enter_architect
from acceptance.test_self_buff_electives import declare, defend, discovered, enter_bandit_fight, equip, receipt, stamina
from acceptance.test_still_anchors import fresh_session
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory

import check_resolution_save
import combat_spatial
import conditions
import db_queries
from combat_participant import CombatParticipant
from condition_catalog import TAUNTED
from condition_restrictions import required_attack_sources

TAUNT = "warrior_taunt"


@pytest.fixture
async def fight(reset_db_pool: str) -> AsyncIterator[MawlingHarness]:
    walk = MawlingHarness()
    try:
        await walk.prepare((4, 4))
        walk.encounter_id = "bandit_ambush"
        await walk.pool.execute(
            """UPDATE players SET data = jsonb_set(data, '{attributes}',
               data->'attributes' || '{"strength":18,"wisdom":8,"charisma":12}')
               WHERE player_id = $1""",
            walk.players[0],
        )
        await equip(walk, TAUNT)
        await enter_bandit_fight(walk)
        state = await walk.reload()
        kael = next(p for p in state.participants if p.type == "companion")
        combat_spatial.place(state, kael.id, combat_spatial.require_spatial(state)["positions"][walk.players[0]])
        await walk.persist()
        yield walk
    finally:
        await walk.close()


def bandit(walk: MawlingHarness) -> CombatParticipant:
    state = walk.sd.combat_state
    assert state is not None
    return next(p for p in state.participants if p.creature_id == "bandit")


def kael(walk: MawlingHarness) -> CombatParticipant:
    state = walk.sd.combat_state
    assert state is not None
    return next(p for p in state.participants if p.type == "companion")


def attack(walk: MawlingHarness, target: str) -> dict:
    foe = bandit(walk)
    return {
        "kind": "attack",
        "actor_id": foe.id,
        "action": foe.action_pool[0]["name"],
        "target_id": target,
        "held_item_id": "",
        "rider": "",
        "reshape": [],
    }


async def land_taunt(walk: MawlingHarness, *, saved: bool = False, queued_attack: bool = False) -> None:
    warrior = walk.players[0]
    row = await discovered(walk, TAUNT)
    foe = bandit(walk)
    before = await stamina(warrior)
    await declare(
        walk,
        {
            "kind": "ability",
            "actor_id": warrior,
            "action": row["id"],
            "targets": [foe.id],
            "argument_type": "",
            "reshape": [],
        },
        attack(walk, kael(walk).id) if queued_attack else defend(foe.id),
    )
    with (
        patch("check_resolution.dice_roll", return_value=_d20(20 if saved else 1)),
        patch("check_resolution_save.roll_participant_save", wraps=check_resolution_save.roll_participant_save) as roll,
    ):
        first = await walk.command("resolve_phase", {})
    roll.assert_called_once()
    assert roll.call_args.args[1:3] == ("wisdom", 13)
    result = receipt(first["packets"], warrior)
    assert result["action"] == TAUNT
    assert result["save_success"] is saved
    assert result["condition_resisted" if saved else "condition_inflicted"] == "taunted"
    assert await stamina(warrior) == before - 2
    state = await walk.reload()
    active = bandit(walk).conditions
    assert required_attack_sources(active) == (() if saved else (warrior,))
    landed = next((c for c in active if c["type"] == TAUNTED), None)
    if saved:
        assert landed is None
    else:
        assert landed is not None and landed["duration"] == 2
    if queued_attack:
        assert state.held_actions[0]["actor_id"] == foe.id
        await resolve_attack(walk, kael(walk).id)
    elif state.beat != "declaration":
        await walk.drain()


async def resolve_attack(walk: MawlingHarness, target: str) -> None:
    warrior = walk.players[0]
    before = await db_queries.get_player(warrior)
    companion_hp = kael(walk).hp_current
    with (
        patch("check_resolution.dice_roll", return_value=_d20(18)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        result = receipt(await walk.drain(), bandit(walk).id)
    assert result["hit"] is True
    after = await db_queries.get_player(warrior)
    assert before is not None and after is not None
    if target == warrior:
        assert after["hp"]["current"] < before["hp"]["current"]
        assert kael(walk).hp_current == companion_hp
    else:
        assert after["hp"] == before["hp"]
        assert kael(walk).hp_current < companion_hp


async def refuse(walk: MawlingHarness, strike: dict) -> None:
    before = await walk.snapshot()
    warrior = (await walk.reload()).get_participant(walk.players[0])
    assert warrior is not None
    error = await walk.command("declare_phase", {"declarations": [strike]}, error=True)
    assert "Taunt" in error and warrior.name in error and warrior.id in error
    assert await walk.snapshot() == before


async def test_taunt_preserves_queued_attack_and_expires_after_next_round(fight: MawlingHarness) -> None:
    await land_taunt(fight, queued_attack=True)
    state = await fight.reload()
    assert state.round_number == 2
    assert next(c for c in bandit(fight).conditions if c["type"] == "taunted")["duration"] == 1
    await fresh_session(fight, state)
    warrior = fight.players[0]
    companion = kael(fight).id
    await refuse(fight, attack(fight, companion))
    await declare(fight, attack(fight, warrior), defend(warrior))
    await resolve_attack(fight, warrior)
    assert (await fight.reload()).round_number == 3
    assert all(c["type"] != "taunted" for c in bandit(fight).conditions)
    await declare(fight, attack(fight, companion), defend(warrior))
    await resolve_attack(fight, companion)


async def test_taunt_keeps_queued_reshape_and_its_original_target(reset_db_pool: str) -> None:
    walk = MawlingHarness()
    try:
        await walk.prepare((20, 20), companion=None, location=WORKS)
        state = await enter_architect(walk)
        target, taunter = walk.players
        encounter = state.architect_encounter
        assert encounter is not None
        owner_id = encounter["owner_id"]
        wall = encounter["structure_ids"][0]
        combat_spatial.place(state, owner_id, pos(0))
        combat_spatial.place(state, target, pos(20, 11))
        combat_spatial.place(state, taunter, pos(10))
        await walk.persist()
        before = await db_queries.get_player(target)
        assert before is not None
        await declare(
            walk,
            defend(target),
            defend(taunter),
            {
                "kind": "attack",
                "actor_id": owner_id,
                "target_id": target,
                "action": "Geometry Strike",
                "held_item_id": "",
                "rider": "",
                "reshape": [{"kind": "move_wall", "wall_id": wall, "start": pos(20, 15), "end": pos(38, 15)}],
            },
        )
        state = await walk.reload()
        owner = state.get_participant(owner_id)
        assert owner is not None
        owner.conditions = conditions.apply_condition(owner.conditions, TAUNTED, source=taunter, duration=2)
        await walk.persist()
        with patch("dice.roll", return_value=_damage_die(12)):
            result = receipt(await walk.drain(), owner_id)
        assert result.get("reshape") == [{"kind": "move_wall", "section_id": wall}], result
        after = await db_queries.get_player(target)
        assert after is not None and after["hp"]["current"] < before["hp"]["current"]
    finally:
        await walk.close()


async def test_successful_wisdom_save_still_costs_stamina(fight: MawlingHarness) -> None:
    await land_taunt(fight, saved=True)
    companion = kael(fight).id
    await declare(fight, attack(fight, companion), defend(fight.players[0]))
    await resolve_attack(fight, companion)


@pytest.mark.parametrize("unavailable", ["fallen", "charmed"])
async def test_taunt_releases_an_unavailable_source(fight: MawlingHarness, unavailable: str) -> None:
    await land_taunt(fight)
    companion = kael(fight).id
    await refuse(fight, attack(fight, companion))
    warrior = (await fight.reload()).get_participant(fight.players[0])
    assert warrior is not None
    if unavailable == "fallen":
        warrior.hp_current = 0
        warrior.is_fallen = True
        fallen = (await fight.persist()).get_participant(warrior.id)
        assert fallen is not None and fallen.is_fallen
    else:
        bandit(fight).conditions = conditions.apply_condition(
            bandit(fight).conditions, "charmed", source=warrior.id, duration=2
        )
        await fight.persist()
    await declare(fight, attack(fight, companion), defend(fight.players[1]))
    await resolve_attack(fight, companion)


async def test_taunt_checks_every_strike_and_allows_defending(fight: MawlingHarness) -> None:
    await land_taunt(fight)
    warrior = fight.players[0]
    foe = bandit(fight)
    action = foe.action_pool[0]["name"]
    foe.multiattack_sequence = {"name": "Double Strike", "attacks": [action, action]}
    await fight.persist()
    await refuse(
        fight,
        {
            "kind": "multiattack",
            "actor_id": foe.id,
            "action": "Double Strike",
            "strikes": [
                {"action": action, "target_id": target, "held_item_id": ""} for target in (warrior, kael(fight).id)
            ],
        },
    )
    await declare(fight, defend(foe.id), defend(warrior))
