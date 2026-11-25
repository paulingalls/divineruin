"""War Cry through equipped ability discovery, registered tools, and combat reloads."""

from collections.abc import AsyncIterator
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_entomb import favor
from acceptance.test_martial_core_kit import enter, weapon_attack
from acceptance.test_self_buff_electives import defend, discovered, equip, receipt, stamina
from acceptance.test_still_anchors import fresh_session
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory

import check_resolution_save
import combat_ability
import combat_hold
import combat_spatial
import conditions
from combat_participant import CombatParticipant
from combat_state import CombatState
from combat_structures import Point, add_wall, line_blocker

WAR_CRY = "warrior_war_cry"
WALL = "war_cry_wall"


@pytest.fixture
async def fight(reset_db_pool: str) -> AsyncIterator[MawlingHarness]:
    walk = MawlingHarness()
    try:
        await walk.prepare((8, 8), companion=None)
        walk.encounter_id = "bandit_ambush"
        await walk.pool.execute(
            """UPDATE players SET data = jsonb_set(data, '{attributes}',
               data->'attributes' || '{"strength":18,"wisdom":8,"charisma":12}')
               WHERE player_id = $1""",
            walk.players[0],
        )
        await equip(walk, WAR_CRY)
        await enter(walk)
        state = await walk.reload()
        [captain] = [p for p in state.participants if p.creature_id == "bandit_captain"]
        captain.hp_current = 0
        captain.is_fallen = True
        *hearing, deafened = bandits(state)
        assert len(hearing) == 3
        deafened.conditions = conditions.apply_condition(deafened.conditions, "deafened", source="test")
        await walk.persist()
        yield walk
    finally:
        await walk.close()


def bandits(state: CombatState) -> list[CombatParticipant]:
    return [p for p in state.participants if p.creature_id == "bandit"]


async def declare(
    walk: MawlingHarness, targets: list[str], *, ally_action: dict | None = None, error: bool = False
) -> dict | str:
    state = await walk.reload()
    actor, ally = walk.players
    return await walk.command(
        "declare_phase",
        {
            "declarations": [
                {
                    "kind": "ability",
                    "actor_id": actor,
                    "action": WAR_CRY,
                    "targets": targets,
                    "argument_type": "",
                    "reshape": [],
                },
                ally_action or defend(ally),
                *(defend(p.id) for p in bandits(state)),
            ]
        },
        error=error,
    )


def frightened(state: CombatState, source: str) -> dict[str, list[dict]]:
    return {
        p.id: active
        for p in state.participants
        if (active := [c for c in p.conditions if c["type"] == "frightened" and c["source"] == source])
    }


def point(x: int, y: int = 0) -> Point:
    return {"x": x, "y": y, "z": 0}


@pytest.mark.parametrize("explicit", [False, True], ids=["targetless", "ignored_target_behind_wall"])
async def test_war_cry_resolves_each_hearing_standing_foe(fight: MawlingHarness, explicit: bool) -> None:
    actor = fight.players[0]
    state = await fight.reload()
    first, second, third, deafened = bandits(state)
    expected = [first.id, second.id, third.id]
    combat_spatial.place(state, actor, point(0))
    combat_spatial.place(state, first.id, point(10))
    wall_x = 5 if explicit else -50
    wall = add_wall(state, WALL, "Slate Wall", point(wall_x, -5), point(wall_x, 5))
    if explicit:
        assert line_blocker(state, actor, first.id) == wall
    deafened.conditions = conditions.apply_condition(deafened.conditions, "frightened", source="ordinary")
    await fight.persist()
    await discovered(fight, WAR_CRY)
    before = await stamina(actor)
    await declare(fight, [first.id] if explicit else [])

    with (
        patch("check_resolution.dice_roll", side_effect=map(_d20, [1, 20, 1, 20, 20, 20])),
        patch("check_resolution_save.roll_participant_save", wraps=check_resolution_save.roll_participant_save) as roll,
    ):
        result = receipt((await fight.command("resolve_phase", {}))["packets"], actor)
        assert [(c.args[0].id, *c.args[1:3], c.kwargs["originating_participant_id"]) for c in roll.call_args_list] == [
            (target_id, "wisdom", 14, actor) for target_id in expected
        ]
        assert_outcomes(result, expected)
        assert await stamina(actor) == before - 5
        saved = await fight.reload()
        assert {action["actor_id"] for action in saved.held_actions} == {*expected, deafened.id}
        assert_frightened(saved, actor, [first.id, third.id])
        await fresh_session(fight, saved)
        await resolve_defenders(fight, saved, actor, [first.id, third.id])
    assert [(c.args[0].id, c.args[1]) for c in roll.call_args_list[3:]] == [(deafened.id, "wis")]
    finished = await fight.reload()
    assert finished.round_number == saved.round_number + 1
    assert finished.beat == "declaration"
    assert not frightened(finished, WAR_CRY)


async def resolve_defenders(walk: MawlingHarness, saved: CombatState, actor: str, frightened_ids: list[str]) -> None:
    resolve = combat_hold._resolve_held

    async def observe(*args, **kwargs) -> dict:
        assert_frightened(args[1], actor, frightened_ids)
        return await resolve(*args, **kwargs)

    with patch("combat_hold._resolve_held", side_effect=observe):
        packets = await walk.drain()
    assert {packet["actor_id"] for packet in packets if packet.get("declaration_type") == "defend"} == {
        held["actor_id"] for held in saved.held_actions
    }


def assert_outcomes(result: dict, expected: list[str]) -> None:
    assert result["resolved"] and result["action"] == WAR_CRY
    assert "condition_applied" not in result
    assert result["condition_targets"] == [expected[0], expected[2]]
    assert [
        (row["target_id"], row["save_success"], row.get("condition_inflicted") or row.get("condition_resisted"))
        for row in result["condition_results"]
    ] == [(target, success, "frightened") for target, success in zip(expected, [False, True, False], strict=True)]
    assert all(row["target"] for row in result["condition_results"])


def assert_frightened(state: CombatState, actor: str, expected: list[str]) -> None:
    landed = frightened(state, WAR_CRY)
    assert set(landed) == set(expected)
    for records in landed.values():
        [record] = records
        assert record["duration"] == 1 and record["originating_participant_id"] == actor


async def test_war_cry_keeps_finalized_recipients_across_two_reloads(fight: MawlingHarness) -> None:
    actor = fight.players[0]
    state = await fight.reload()
    first, second, third, deafened = bandits(state)
    expected = [first.id, second.id, third.id]
    warrior = state.get_participant(actor)
    assert warrior is not None
    warrior.conditions = conditions.apply_condition(warrior.conditions, "charmed", source=deafened.id)
    await fight.persist()
    await favor(fight)
    before = await stamina(actor)
    await declare(fight, [])
    with (
        patch("check_resolution.dice_roll", side_effect=map(_d20, [1, 20, 1])),
        patch("check_resolution_save.roll_participant_save", wraps=check_resolution_save.roll_participant_save) as roll,
        patch("combat_ability._land_condition_on_one", wraps=combat_ability._land_condition_on_one) as land,
    ):
        pending = (await fight.command("resolve_phase", {}))["fate_offer"]
        assert (pending["roller_id"], pending["roll_kind"]) == (first.id, "save")
        assert await stamina(actor) == before - 5
        assert not frightened(await fight.reload(), WAR_CRY)

        response = await fight.command(
            "activate", {"id": "zhael_fates_thread", "offer_id": pending["offer_id"], "keep": "original"}
        )
        assert response["fate_offer"]["roller_id"] == second.id
        saved = await fight.reload()
        assert_frightened(saved, actor, [first.id])
        assert saved.ally_continuation is not None
        [finalized] = saved.ally_continuation["steps"][WAR_CRY]["condition_results"]
        assert (finalized["target_id"], finalized["save_success"]) == (first.id, False)
        assert await stamina(actor) == before - 5
        saved.participants.reverse()
        fourth = saved.get_participant(deafened.id)
        assert fourth is not None
        fourth.conditions = conditions.remove_condition(fourth.conditions, "deafened")
        await fresh_session(fight, await fight.persist())

        response = await fight.command("resolve_phase", {})
        assert response["fate_offer"]["roller_id"] == third.id
        saved = await fight.reload()
        assert_frightened(saved, actor, [first.id])
        assert await stamina(actor) == before - 5
        await fresh_session(fight, saved)

        finished = await fight.command("resolve_phase", {})
        assert_outcomes(receipt(finished["packets"], actor), expected)
        assert_frightened(await fight.reload(), actor, [first.id, third.id])
        await fight.drain()
    assert [call.args[0].id for call in roll.call_args_list] == expected
    assert [call.args[1] for call in land.call_args_list] == [first.id, third.id]
    assert await stamina(actor) == before - 5


async def test_war_cry_refuses_without_recipients(fight: MawlingHarness) -> None:
    actor = fight.players[0]
    before = await stamina(actor)
    state = await fight.reload()
    for bandit in bandits(state):
        bandit.conditions = conditions.apply_condition(bandit.conditions, "deafened", source="test")
    saved = await fight.persist()
    assert "requires a standing foe who can hear" in await declare(fight, [], error=True)
    assert await stamina(actor) == before
    assert (await fight.reload()).to_dict() == saved.to_dict()


async def test_war_cry_wastes_no_stamina_when_last_recipient_falls_before_its_packet(fight: MawlingHarness) -> None:
    actor, ally = fight.players
    state = await fight.reload()
    last_hearing, *deafened = bandits(state)
    for bandit in deafened:
        bandit.conditions = conditions.apply_condition(bandit.conditions, "deafened", source="test")
    last_hearing.hp_current = 1
    helper = state.get_participant(ally)
    assert helper is not None
    helper.initiative = 100
    combat_spatial.place(state, ally, combat_spatial.require_spatial(state)["positions"][last_hearing.id])
    await fight.persist()
    before = await stamina(actor)
    await declare(fight, [], ally_action=weapon_attack(ally, last_hearing.id, ""))
    with (
        patch("check_resolution.dice_roll", return_value=_d20(19)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(7)),
    ):
        packets = (await fight.command("resolve_phase", {}))["packets"]
    assert receipt(packets, ally)["target_hp_status"] == "fallen"
    wasted = receipt(packets, actor)
    assert not wasted["resolved"] and "no standing foes who can hear" in wasted["reason"]
    assert await stamina(actor) == before
