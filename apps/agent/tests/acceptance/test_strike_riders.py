"""Rogue strike riders through the registered combat tools and persisted phases."""

import json
from collections.abc import AsyncIterator
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance._enemy_opportunity_helpers import declare, move, resolve_allies, strikes
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_entomb import favor
from acceptance.test_architect_fight import pos
from acceptance.test_martial_core_kit import weapon_attack
from acceptance.test_opportunity_strike import participant
from acceptance.test_self_buff_electives import bandit_attack, discovered, enter_bandit_fight, equip, receipt, stamina
from acceptance.test_still_anchors import fresh_session
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory
from weapon_fixtures import DAGGER

import combat_spatial
import conditions
from session_data import CombatState

CRIPPLING = "rogue_crippling_strike"
STUDY = "rogue_exploit_weakness"


@pytest.fixture
async def rogue(reset_db_pool: str) -> AsyncIterator[MawlingHarness]:
    walk = MawlingHarness()
    try:
        await walk.prepare((8, 8), companion=None)
        walk.encounter_id = "bandit_ambush"
        await walk.pool.execute(
            "UPDATE players SET data = data || $2::jsonb WHERE player_id = $1",
            walk.players[0],
            json.dumps({"class": "rogue", "equipment": {"main_hand": DAGGER}}),
        )
        await equip(walk, CRIPPLING)
        await equip(walk, STUDY)
        yield walk
    finally:
        await walk.close()


async def enter_ambush(walk: MawlingHarness, *, ally_x: int = 0) -> tuple[str, str]:
    foe = await enter_bandit_fight(walk)
    state = await walk.reload()
    walk.enemies = [p.id for p in state.participants if not p.is_ally]
    other = next(p for p in state.participants if p.id != foe and p.creature_id == "bandit")
    other.hp_current = other.hp_max = 100
    placements = {enemy: pos(80) for enemy in walk.enemies}
    placements.update({foe: pos(0), other.id: pos(3), walk.players[0]: pos(0), walk.players[1]: pos(ally_x)})
    combat_spatial.require_spatial(state)["positions"].update(placements)
    await walk.persist()
    return foe, other.id


async def restart(walk: MawlingHarness) -> CombatState:
    members = list(walk.sd.party.members)
    state = await walk.reload()
    await fresh_session(walk, state)
    walk.sd.party.members.extend(member for member in members if member.player_id != walk.players[0])
    return state


def study(actor: str, *targets: str, action: str = STUDY) -> dict:
    return {
        "kind": "ability",
        "actor_id": actor,
        "action": action,
        "targets": list(targets),
        "argument_type": "",
        "reshape": [],
    }


def marker(walk: MawlingHarness, actor: str, kind: str) -> dict | None:
    state = walk.sd.combat_state
    assert state is not None
    return next((c for c in participant(state, actor).conditions if c["type"] == kind), None)


@contextmanager
def rolls(face: int):
    with (
        patch("check_resolution.dice_roll", return_value=_d20(face)) as d20,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(2)) as damage,
    ):
        yield d20, damage


@pytest.mark.parametrize("hit", [True, False])
async def test_crippling_approach_reloads_and_expires(rogue: MawlingHarness, hit: bool) -> None:
    actor, ally = rogue.players
    foe, _ = await enter_ambush(rogue, ally_x=-75)
    row = await discovered(rogue, CRIPPLING)
    rider = row["declaration"]["rider"]
    assert rider == "crippling_strike"
    before = await stamina(actor)
    approach = await bandit_attack(rogue, foe, ally)
    await declare(rogue, weapon_attack(actor, foe, rider, weapon=DAGGER["name"]), approach)
    with rolls(17 if hit else 1) as (d20, _):
        attack = receipt(await resolve_allies(rogue), actor)
        assert attack["hit"] is hit
        d20.assert_called_once()
    assert await stamina(actor) == before - 3
    await restart(rogue)
    allowance = 15 if hit else 30
    assert bool(marker(rogue, foe, "crippled")) is hit
    assert combat_spatial.facts(rogue.sd.combat_state, actor)["speeds_ft"][foe] == allowance
    with rolls(1):
        moved = receipt(await rogue.drain(), foe)
    assert moved["movement_spent_ft"] == allowance and moved["attack_resolved"] is False
    state = await rogue.reload()
    spatial = combat_spatial.require_spatial(state)
    assert spatial["positions"][foe] == pos(-allowance)
    assert marker(rogue, foe, "crippled") is None
    assert combat_spatial.facts(state, actor)["speeds_ft"][foe] == spatial["speeds"][foe] == 30
    combat_spatial.place(state, foe, pos(0))
    await rogue.persist()
    await declare(rogue, approach)
    with rolls(1):
        assert receipt(await rogue.drain(), foe)["movement_spent_ft"] == 30
    assert await stamina(actor) == before - 3


async def slow(rogue: MawlingHarness, actor: str) -> None:
    state = await rogue.reload()
    player = participant(state, actor)
    player.conditions = conditions.apply_condition(player.conditions, "crippled", source=CRIPPLING, duration=1)
    await rogue.persist()
    await restart(rogue)


@pytest.mark.parametrize("leaves_reach", [False, True])
async def test_persisted_slow_limits_player_move(rogue: MawlingHarness, leaves_reach: bool) -> None:
    actor = rogue.players[0]
    foe, _ = await enter_ambush(rogue)
    direction = -1 if leaves_reach else 1
    state = await rogue.reload()
    for enemy in rogue.enemies:
        if enemy != foe or not leaves_reach:
            combat_spatial.place(state, enemy, pos(80))
    if leaves_reach:
        await favor(rogue)
    await rogue.persist()
    await slow(rogue, actor)
    before = await rogue.snapshot()
    error = await rogue.command("declare_phase", {"declarations": [move(actor, 16 * direction)]}, error=True)
    assert "exceeds speed 15" in error
    assert await rogue.snapshot() == before
    await declare(rogue, move(actor, 15 * direction))
    with rolls(18):
        first = await rogue.command("resolve_phase", {})
        if leaves_reach:
            assert first["fate_offer"]["roller_id"] == foe
            state = await restart(rogue)
            continuation = state.ally_continuation
            assert continuation is not None
            assert continuation["steps"]["movement_route"]["budget"]["remaining"] == 10
            packets = await resolve_allies(rogue)
            assert len(strikes(packets)) == 1
        else:
            packets = first["packets"]
        assert receipt(packets, actor)["movement_spent_ft"] == 15
        await rogue.drain()
    spatial = combat_spatial.require_spatial(await rogue.reload())
    assert spatial["positions"][actor] == pos(15 * direction)
    assert spatial["speeds"][actor] == 30
    assert marker(rogue, actor, "crippled") is None
    await declare(rogue, move(actor, 45 * direction))
    assert receipt(await resolve_allies(rogue), actor)["movement_spent_ft"] == 30


async def test_slowed_dash_approach(rogue: MawlingHarness) -> None:
    actor = rogue.players[0]
    foe, _ = await enter_ambush(rogue)
    state = await rogue.reload()
    for enemy in rogue.enemies:
        combat_spatial.place(state, enemy, pos(120))
    await rogue.persist()
    await slow(rogue, actor)
    for allowance in (30, 60):
        await declare(rogue, weapon_attack(actor, foe, "dash", weapon=DAGGER["name"]))
        assert receipt(await rogue.drain(), actor)["movement_spent_ft"] == allowance


@pytest.mark.parametrize("face", [17, 20])
async def test_study_reloads_and_maximizes_next_round_sneak(rogue: MawlingHarness, face: int) -> None:
    actor = rogue.players[0]
    foe, _ = await enter_ambush(rogue)
    row = await discovered(rogue, STUDY)
    assert "declaration" not in row
    before = await stamina(actor)
    await declare(rogue, study(actor, foe, action=row["id"]))
    with rolls(1) as (d20, _):
        result = receipt(await rogue.drain(), actor)
        d20.assert_not_called()
    assert result["target_id"] == foe and "hit" not in result
    assert await stamina(actor) == before - 4
    state = await restart(rogue)
    mark = marker(rogue, actor, "studied_weakness")
    assert mark is not None and mark["source"] == foe

    hp = participant(state, foe).hp_current
    await declare(rogue, weapon_attack(actor, foe, "", weapon=DAGGER["name"]))
    with rolls(face) as (_, damage):
        hit = receipt(await resolve_allies(rogue), actor)
    count = 4 if face == 20 else 2
    assert hit["sneak_attack_dice"] == f"{count}d6"
    assert hit["sneak_attack_raw_damage"] == count * 6
    assert [call.args[0] for call in damage.call_args_list] == ["1d8"] * (count // 2)
    state = await rogue.reload()
    assert participant(state, foe).hp_current == hp - hit["damage"]
    assert "studied_weakness" in hit["consumed_conditions"]
    assert marker(rogue, actor, "studied_weakness") is None


async def test_other_target_preserves_study_until_expiry(rogue: MawlingHarness) -> None:
    actor = rogue.players[0]
    foe, other = await enter_ambush(rogue)
    await declare(rogue, study(actor, foe))
    await rogue.drain()
    await restart(rogue)
    for target in (other, foe):
        await declare(rogue, weapon_attack(actor, target, "", weapon=DAGGER["name"]))
        with rolls(17) as (_, damage):
            hit = receipt(await resolve_allies(rogue), actor)
        assert hit["sneak_attack_raw_damage"] == 2
        assert [call.args[0] for call in damage.call_args_list] == ["1d8", "2d6"]
        await rogue.reload()
        if target == other:
            mark = marker(rogue, actor, "studied_weakness")
            assert mark is not None and mark["source"] == foe
        await rogue.drain()
        assert marker(rogue, actor, "studied_weakness") is None
