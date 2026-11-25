"""Blade Flurry through registered combat commands and saved round state."""

import json
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die, _dice_events
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_entomb import favor
from acceptance.test_cleave_and_whirlwind import battlefield
from acceptance.test_martial_core_kit import declare
from acceptance.test_opportunity_strike import participant
from acceptance.test_self_buff_electives import discovered, receipt, stamina
from acceptance.test_still_anchors import fresh_session
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_strike_riders_guards import activate_variant

import check_resolution_attack
import combat_enhancers
import conditions
import db_queries
from combat_support import _resolve_attack_packet

FLURRY = "rogue_blade_flurry"
KELDARAN = "rogue_blade_flurry_keldaran"
WEAPON = {"name": "Shortsword", "damage": "1d6", "damage_type": "piercing", "properties": ["finesse"]}
FACES = (3, 15, 4, 16, 5, 17)


@pytest.fixture
async def rogue(reset_db_pool: str, request: pytest.FixtureRequest) -> AsyncIterator[MawlingHarness]:
    walk = MawlingHarness()
    try:
        await walk.prepare(getattr(request, "param", (9,)), companion=None)
        await walk.pool.execute(
            "UPDATE players SET data = data || $2::jsonb WHERE player_id = $1",
            walk.players[0],
            json.dumps({"class": "rogue", "equipment": {"main_hand": WEAPON}}),
        )
        walk.encounter_id = "bandit_ambush"
        yield walk
    finally:
        await walk.close()


async def bandit(walk: MawlingHarness, *, prone: bool = True, hp: int = 100) -> str:
    target_id, *_ = await battlefield(walk, FLURRY, (3,))
    state = await walk.reload()
    target = participant(state, target_id)
    target.hp_current = hp
    if prone:
        target.conditions = conditions.apply_condition(target.conditions, "prone")
    await walk.persist()
    return target_id


@contextmanager
def rolls(faces: tuple[int, ...], damage: tuple[int, ...]) -> Iterator[tuple[MagicMock, MagicMock]]:
    with (
        patch("check_resolution.dice_roll", side_effect=map(_d20, faces)) as d20,
        patch("check_resolution_attack.dice_roll", side_effect=map(_damage_die, damage)) as dice,
    ):
        yield d20, dice


def attack_events(walk: MawlingHarness) -> list[tuple[int, int]]:
    return [(e["roll"], e["modifier"]) for e in _dice_events(walk.sd.room) if e["roll_type"] == "attack"]


async def ordinary_attack(walk: MawlingHarness, target_id: str) -> dict:
    state = await walk.reload()
    actor = participant(state, walk.players[0])
    weapon = next(action for action in actor.action_pool if action["name"] == WEAPON["name"])
    with rolls(
        (6, 18),
        (
            4,
            9,
        ),
    ):
        result = await _resolve_attack_packet(
            walk.sd,
            actor,
            weapon,
            participant(state, target_id),
            combat_state=state,
            conn=walk.pool,
        )
    await walk.persist()
    return result


@pytest.mark.parametrize("already_spent", [False, True])
async def test_three_hits_at_minus_two_each_add_sneak_attack(rogue: MawlingHarness, already_spent: bool) -> None:
    actor_id = rogue.players[0]
    target_id = await bandit(rogue)
    if already_spent:
        assert (await ordinary_attack(rogue, target_id))["sneak_attack_dice"] == "3d6"
    state = await rogue.reload()
    actor = participant(state, actor_id)
    actor.enhancers = [combat_enhancers.EXTRA_ATTACK]
    weapon_mod = (
        check_resolution_attack.attack_modifier({"attributes": actor.attributes, "level": actor.level}, WEAPON)
        + actor.attack_mod
    )
    damage_mod = check_resolution_attack.weapon_attribute_modifier({"attributes": actor.attributes}, WEAPON)
    before_hp = participant(state, target_id).hp_current
    round_number = state.round_number
    await rogue.persist()
    before_stamina = await stamina(actor_id)
    await declare(rogue, (await discovered(rogue, FLURRY))["id"], [target_id])
    event_offset = len(attack_events(rogue))
    with rolls(FACES, (3, 9, 4, 10, 5, 11)) as (d20, damage):
        result = receipt((await rogue.command("resolve_phase", {}))["packets"], actor_id)
    assert d20.call_count == 6
    assert [call.args[0] for call in damage.call_args_list] == ["1d6", "3d6"] * 3
    assert attack_events(rogue)[event_offset:] == [(face, weapon_mod - 2) for face in FACES[1::2]]
    assert [
        (s["roll"], s["sneak_attack_dice"], s["sneak_attack_raw_damage"], s["damage"]) for s in result["attacks"]
    ] == [(15, "3d6", 9, 12 + damage_mod), (16, "3d6", 10, 14 + damage_mod), (17, "3d6", 11, 16 + damage_mod)]
    state = await rogue.reload()
    assert participant(state, target_id).hp_current == before_hp - (42 + 3 * damage_mod)
    assert await stamina(actor_id) == before_stamina - 4

    ordinary = await ordinary_attack(rogue, target_id)
    assert (ordinary["sneak_attack_dice"], ordinary["damage"]) == (None, 4 + damage_mod)
    assert attack_events(rogue)[-1] == (18, weapon_mod)
    assert participant(await rogue.reload(), actor_id).sneak_attack_round == round_number


@pytest.mark.parametrize(("action", "cost"), [(FLURRY, (4, 0)), (KELDARAN, (3, 1))])
async def test_target_falls_on_first_swing(rogue: MawlingHarness, action: str, cost: tuple[int, int]) -> None:
    target_id = await bandit(rogue, hp=1)
    actor_id = rogue.players[0]
    if action == KELDARAN:
        await activate_variant(rogue, FLURRY, KELDARAN)
    before = await db_queries.get_player(actor_id)
    assert before is not None
    await declare(rogue, action, [target_id])
    with rolls(FACES[:2], (4, 9)) as (d20, damage):
        result = receipt(await rogue.drain(), actor_id)
    assert d20.call_count == damage.call_count == 2
    assert "attacks" not in result
    assert (result["roll"], result["sneak_attack_dice"], result["target_fallen"]) == (15, "3d6", True)
    target = participant(await rogue.reload(), target_id)
    assert target.hp_current == 0 and target.is_fallen
    after = await db_queries.get_player(actor_id)
    assert after is not None
    assert tuple(before[pool]["current"] - after[pool]["current"] for pool in ("stamina", "focus")) == cost
    if action == KELDARAN:
        assert result["variant_id"] == KELDARAN
        assert result["cultural_attribution"] == "Keldaran Holds technique"


async def test_remaining_swings_resume_once(rogue: MawlingHarness) -> None:
    target_id = await bandit(rogue)
    actor_id = rogue.players[0]
    actor = participant(await rogue.reload(), actor_id)
    weapon_mod = (
        check_resolution_attack.attack_modifier({"attributes": actor.attributes, "level": actor.level}, WEAPON)
        + actor.attack_mod
    )
    damage_mod = check_resolution_attack.weapon_attribute_modifier({"attributes": actor.attributes}, WEAPON)
    await favor(rogue)
    await declare(rogue, FLURRY, [target_id])
    spent = (await stamina(actor_id)) - 4
    with rolls(FACES, (3, 9, 4, 10, 5, 11)) as (d20, damage):
        assert (await rogue.command("resolve_phase", {}))["fate_offer"]["roller_id"] == actor_id
        assert (await rogue.command("resolve_phase", {}))["fate_offer"]["roller_id"] == actor_id
        saved = await rogue.reload()
        assert saved.ally_continuation
        cursor = saved.ally_continuation["attack"]
        assert len(cursor["summaries"]) == 1
        assert cursor["prepared"]["d20"]["modifier"] == weapon_mod - 2
        assert (d20.call_count, damage.call_count) == (4, 2)
        assert participant(saved, target_id).hp_current == 100 - (12 + damage_mod)
        assert await stamina(actor_id) == spent
        await fresh_session(rogue, saved)
        assert (await rogue.command("resolve_phase", {}))["fate_offer"]["roller_id"] == actor_id
        wrapped = await rogue.command("resolve_phase", {})
        result = receipt(wrapped["settled_fate"]["packets"], actor_id)
        assert [(s["roll"], s["sneak_attack_dice"], s["damage"]) for s in result["attacks"]] == [
            (15, "3d6", 12 + damage_mod),
            (16, "3d6", 14 + damage_mod),
            (17, "3d6", 16 + damage_mod),
        ]
        assert attack_events(rogue) == [(face, weapon_mod - 2) for face in FACES[1::2]]
        assert actor_id not in {packet["actor_id"] for packet in wrapped["packets"]}
        await rogue.command("resolve_phase", {}, error=True)
    assert d20.call_count == damage.call_count == 6
    final = await rogue.reload()
    assert final.ally_continuation is None
    assert participant(final, target_id).hp_current == 100 - (42 + 3 * damage_mod)
    assert await stamina(actor_id) == spent
