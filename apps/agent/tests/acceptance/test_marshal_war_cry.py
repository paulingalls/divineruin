"""Marshal War Cry at the registered combat and Fate tool boundaries."""

from collections.abc import AsyncIterator
from contextlib import AbstractContextManager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_entomb import favor
from acceptance.test_martial_core_kit import enter, weapon_attack
from acceptance.test_self_buff_electives import defend, discovered, equip, receipt, stamina
from acceptance.test_still_anchors import fresh_session
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_war_cry import bandits, frightened, point

import check_resolution_save
import combat_hold
import combat_spatial
import conditions
import db_mutations
from combat_participant import CombatParticipant
from combat_state import CombatState

CRY = "marshal_war_cry"
RALLY = "war_cry_rally"


@pytest.fixture
async def fight(reset_db_pool: str) -> AsyncIterator[MawlingHarness]:
    walk = MawlingHarness()
    try:
        await walk.prepare((4, 8))
        marshal, ally = walk.players
        walk.encounter_id = "bandit_ambush"
        await walk.pool.execute(
            """UPDATE players SET data = data || '{"class":"marshal"}' ||
               jsonb_build_object('attributes', data->'attributes' || '{"strength":18,"charisma":8}')
               WHERE player_id = $1""",
            marshal,
        )
        await equip(walk, CRY)
        await db_mutations.set_player_flag(ally, "extra_attack", True)
        await enter(walk)
        state = await walk.reload()
        for actor_id, x, initiative in ((marshal, 0, 100), (ally, 40, 90), (kael(state).id, 5, 80)):
            participant = state.get_participant(actor_id)
            assert participant is not None
            participant.initiative = initiative
            combat_spatial.place(state, actor_id, point(x))
        [captain] = [p for p in state.participants if p.creature_id == "bandit_captain"]
        captain.hp_current, captain.is_fallen = 0, True
        for foe, x in zip(bandits(state), (10, 30, 40, 10), strict=True):
            combat_spatial.place(state, foe.id, point(x))
            foe.hp_current = foe.hp_max = 100
        deaf = bandits(state)[-1]
        deaf.conditions = conditions.apply_condition(deaf.conditions, "deafened", source="test")
        await walk.persist()
        yield walk
    finally:
        await walk.close()


def kael(state: CombatState) -> CombatParticipant:
    return next(p for p in state.participants if p.type == "companion")


async def declare(
    walk: MawlingHarness, *actions: dict, cry: bool = True, error: bool = False, targets: tuple[str, ...] = ()
) -> dict | str:
    state = await walk.reload()
    by_actor = {action["actor_id"]: action for action in actions}
    marshal = walk.players[0]
    if cry:
        by_actor[marshal] = {
            "kind": "ability",
            "actor_id": marshal,
            "action": CRY,
            "targets": list(targets),
            "argument_type": "",
            "reshape": [],
        }
    return await walk.command(
        "declare_phase",
        {"declarations": [by_actor.get(p.id, defend(p.id)) for p in state.participants if not p.is_fallen]},
        error=error,
    )


def rallies(state: CombatState) -> dict[str, list[dict]]:
    return {p.id: active for p in state.participants if (active := [c for c in p.conditions if c["type"] == RALLY])}


def save_spy() -> AbstractContextManager[MagicMock]:
    return patch("check_resolution_save.roll_participant_save", wraps=check_resolution_save.roll_participant_save)


async def test_nearby_foes_save_and_fear_expires_without_a_tick(fight: MawlingHarness) -> None:
    marshal = fight.players[0]
    state = await fight.reload()
    first, second, far, deaf = bandits(state)
    deaf.conditions = conditions.apply_condition(deaf.conditions, "frightened", source="ordinary")
    await fight.persist()
    await discovered(fight, CRY)
    before = await stamina(marshal)
    await declare(fight, targets=(far.id,))
    with patch("check_resolution.dice_roll", side_effect=map(_d20, [1, 20, 20, 20, 20])), save_spy() as saves:
        result = receipt((await fight.command("resolve_phase", {}))["packets"], marshal)
        assert result["resolved"] and result["action"] == CRY
        assert result["condition_targets"] == [first.id] and "condition_applied" not in result
        assert [(row["target_id"], row["save_success"]) for row in result["condition_results"]] == [
            (first.id, False),
            (second.id, True),
        ]
        assert [(call.args[0].id, *call.args[1:3]) for call in saves.call_args_list] == [
            (first.id, "wisdom", 13),
            (second.id, "wisdom", 13),
        ]
        assert await stamina(marshal) == before - 3

        saved = await fight.reload()
        landed = frightened(saved, CRY)
        assert set(landed) == {first.id}
        [fear] = landed[first.id]
        assert (fear["duration"], fear["originating_participant_id"]) == (1, marshal)
        await fresh_session(fight, saved)
        resolve = combat_hold._resolve_held

        async def observe(*args: Any, **kwargs: Any) -> dict:
            assert frightened(args[1], CRY) == landed
            return await resolve(*args, **kwargs)

        with patch("combat_hold._resolve_held", side_effect=observe) as held:
            await fight.drain()
        assert held.called
        assert [(call.args[0].id, call.args[1]) for call in saves.call_args_list[2:]] == [(deaf.id, "wis")]
    finished = await fight.reload()
    assert finished.beat == "declaration" and finished.round_number == saved.round_number + 1
    assert not frightened(finished, CRY)


async def test_party_attack_bonus_lasts_for_the_round(fight: MawlingHarness) -> None:
    marshal, ally = fight.players
    state = await fight.reload()
    target = bandits(state)[2].id
    attack = weapon_attack(ally, target, "")
    await declare(fight, attack)
    with (
        patch("check_resolution.dice_roll", return_value=_d20(19)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(3)),
    ):
        packets = (await fight.command("resolve_phase", {}))["packets"]
        assert set(receipt(packets, marshal)["rally_targets"]) == {ally, kael(state).id}
        boosted = receipt(packets, ally)["attacks"]
        saved = await fight.reload()
        assert set(rallies(saved)) == {ally, kael(state).id}
        await fresh_session(fight, saved)
        await fight.drain()
        assert not rallies(await fight.reload())
        await declare(fight, attack, cry=False)
        normal = receipt((await fight.command("resolve_phase", {}))["packets"], ally)["attacks"]
    assert len(boosted) == len(normal) == 2
    for buffed, plain in zip(boosted, normal, strict=True):
        assert buffed["roll"] == plain["roll"] == 19
        assert buffed["attack_total"] == plain["attack_total"] + 1


async def test_recipient_outcomes_and_payment_survive_reload(fight: MawlingHarness) -> None:
    marshal, ally = fight.players
    state = await fight.reload()
    first, second, far, deaf = bandits(state)
    actor = state.get_participant(marshal)
    assert actor is not None
    actor.conditions = conditions.apply_condition(actor.conditions, "charmed", source=deaf.id)
    await fight.persist()
    await favor(fight)
    before = await stamina(marshal)
    await declare(fight)
    with patch("check_resolution.dice_roll", return_value=_d20(1)), save_spy() as saves:
        pending = await fight.command("resolve_phase", {})
        assert pending["fate_offer"]["roller_id"] == first.id
        assert not pending["packets"] and not rallies(await fight.reload())
        assert await stamina(marshal) == before - 3
        response = await fight.command(
            "activate", {"id": "zhael_fates_thread", "offer_id": pending["fate_offer"]["offer_id"], "keep": "original"}
        )
        assert response["fate_offer"]["roller_id"] == second.id and not response["packets"]
        saved = await fight.reload()
        assert not rallies(saved)
        assert saved.ally_continuation is not None
        step = saved.ally_continuation["steps"][CRY]
        assert step["cost_paid"] and step["target_ids"] == [first.id, second.id]
        [finalized] = step["condition_results"]
        assert (finalized["target_id"], finalized["save_success"]) == (first.id, False)
        assert await stamina(marshal) == before - 3

        saved.participants.reverse()
        for target in (far.id, deaf.id):
            combat_spatial.place(saved, target, point(10))
            newcomer = saved.get_participant(target)
            assert newcomer is not None
            newcomer.conditions = conditions.remove_condition(newcomer.conditions, "deafened")
        await fresh_session(fight, await fight.persist())
        result = receipt((await fight.command("resolve_phase", {}))["packets"], marshal)
    assert result["resolved"] and result["condition_targets"] == [first.id, second.id]
    assert [row["target_id"] for row in result["condition_results"]] == [first.id, second.id]
    assert [call.args[0].id for call in saves.call_args_list] == [first.id, second.id]
    assert await stamina(marshal) == before - 3
    finished = await fight.reload()
    assert set(frightened(finished, CRY)) == {first.id, second.id}
    assert all(len(records) == 1 for records in frightened(finished, CRY).values())
    assert set(result["rally_targets"]) == {ally, kael(finished).id}
    assert all(len(records) == 1 for records in rallies(finished).values())


@pytest.mark.parametrize("falls_before_cry", [False, True])
async def test_no_nearby_enemy_still_rallies_the_party(fight: MawlingHarness, falls_before_cry: bool) -> None:
    marshal, ally = fight.players
    state = await fight.reload()
    first, second, far, deaf = bandits(state)
    for foe in (first, second, deaf):
        combat_spatial.place(state, foe.id, point(45))
    if falls_before_cry:
        first.hp_current = 1
        combat_spatial.place(state, first.id, point(5))
        combat_spatial.place(state, ally, point(5))
        helper = state.get_participant(ally)
        assert helper is not None
        helper.initiative = 110
    await fight.persist()
    before = await stamina(marshal)
    await declare(fight, weapon_attack(ally, first.id if falls_before_cry else far.id, ""))
    with (
        patch("check_resolution.dice_roll", return_value=_d20(19)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(7)),
        save_spy() as saves,
    ):
        packets = (await fight.command("resolve_phase", {}))["packets"]
    if falls_before_cry:
        assert receipt(packets, ally)["target_hp_status"] == "fallen"
    else:
        first_swing, *_ = receipt(packets, ally)["attacks"]
        assert first_swing["attack_total"] == 19 + 1 + 2 + 1
    rally = receipt(packets, marshal)
    assert rally["resolved"] and rally["condition_results"] == rally["condition_targets"] == []
    assert set(rally["rally_targets"]) == {ally, kael(state).id}
    assert await stamina(marshal) == before - 3
    saves.assert_not_called()
