"""Warrior multi-target abilities through the registered combat commands."""

from collections.abc import AsyncIterator
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_entomb import favor
from acceptance.test_architect_fight import pos
from acceptance.test_martial_core_kit import declare, enter
from acceptance.test_opportunity_strike import participant
from acceptance.test_self_buff_electives import discovered, receipt, stamina
from acceptance.test_still_anchors import fresh_session
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory

import ability_persistence
import combat_enhancers
import combat_spatial
import conditions

CLEAVE = "warrior_cleaving_blow"
WHIRLWIND = "warrior_whirlwind"


@pytest.fixture
async def warrior(reset_db_pool: str, request: pytest.FixtureRequest) -> AsyncIterator[MawlingHarness]:
    walk = MawlingHarness()
    try:
        await walk.prepare(getattr(request, "param", (10,)), companion=None)
        walk.encounter_id = "bandit_ambush"
        yield walk
    finally:
        await walk.close()


async def battlefield(
    walk: MawlingHarness, ability: str, distances: tuple[int, ...], *, actor: str | None = None
) -> list[str]:
    actor = walk.players[0] if actor is None else actor
    await ability_persistence.set_elective_equipped(actor, ability, True, conn=walk.pool)
    await enter(walk)
    state = await walk.reload()
    foes = sorted(p.id for p in state.participants if p.creature_id == "bandit")
    combat_spatial.place(state, actor, pos(0))
    for foe in state.participants:
        if not foe.is_ally:
            foe.hp_current = foe.hp_max = 100
            foe.ac = 10
            combat_spatial.place(state, foe.id, pos(80))
    for foe, distance in zip(foes, distances, strict=False):
        combat_spatial.place(state, foe, pos(distance))
    await walk.persist()
    return foes


@pytest.mark.parametrize(
    ("faces", "blinded", "expected_faces", "expected_damage"),
    [
        ((8, 16), False, (16, 8), (5, 7)),
        ((16, 8), True, (16, 8), (5, 7)),
        ((8, 16), True, (8, 8), (5, 7)),
        ((1, 20), False, (20, 1), (11, 0)),
    ],
)
async def test_cleave_uses_the_shared_pair_in_declaration_order(
    warrior: MawlingHarness,
    faces: tuple[int, int],
    blinded: bool,
    expected_faces: tuple[int, int],
    expected_damage: tuple[int, int],
) -> None:
    first, second, *_ = await battlefield(warrior, CLEAVE, (3, 5))
    state = await warrior.reload()
    prone = participant(state, second)
    prone.conditions = conditions.apply_condition(prone.conditions, "prone")
    prone.ac = 5 if blinded else 15
    participant(state, first).ac = 5
    if blinded:
        attacker = participant(state, warrior.players[0])
        attacker.conditions = conditions.apply_condition(attacker.conditions, "blinded")
    await warrior.persist()
    await declare(warrior, (await discovered(warrior, CLEAVE))["id"], [second, first])
    actor = warrior.players[0]
    before = await stamina(actor)
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(face) for face in faces]) as d20,
        patch("check_resolution_attack.dice_roll", side_effect=[_damage_die(4), _damage_die(6)]) as damage,
    ):
        result = receipt(await warrior.drain(), actor)
    assert d20.call_count == 2
    assert [call.args[0] for call in damage.call_args_list] == ["1d8", "1d8"]
    assert [(s["target_id"], s["roll"], s["damage"]) for s in result["attacks"]] == list(
        zip((second, first), expected_faces, expected_damage, strict=True)
    ), result
    assert result["damage"] == sum(expected_damage)
    assert result["critical"] is (faces[1] == 20)
    state = await warrior.reload()
    assert [participant(state, foe).hp_current for foe in (second, first)] == [100 - n for n in expected_damage]
    assert await stamina(actor) == before - 4


@pytest.mark.parametrize(("falls", "reach"), [(False, 5), (True, 5), (False, 10)])
async def test_whirlwind_reaches_each_foe_once(warrior: MawlingHarness, falls: bool, reach: int) -> None:
    actor = warrior.players[0]
    if reach == 10:
        await warrior.pool.execute(
            """UPDATE players SET data = jsonb_set(data, '{equipment,main_hand,properties}', '["reach"]')
               WHERE player_id = $1""",
            actor,
        )
    first, second, third, outside = await battlefield(warrior, WHIRLWIND, (2, 3, reach, reach + 1))
    state = await warrior.reload()
    participant(state, actor).enhancers = [combat_enhancers.EXTRA_ATTACK]
    state.participants.reverse()
    state.initiative_order.reverse()
    if falls:
        participant(state, first).hp_current = 2
    await warrior.persist()
    await declare(warrior, (await discovered(warrior, WHIRLWIND))["id"], [])
    before = await stamina(actor)
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(face) for face in (15, 16, 17)]) as d20,
        patch("check_resolution_attack.dice_roll", side_effect=[_damage_die(face) for face in (4, 6, 8)]) as damage,
    ):
        result = receipt(await warrior.drain(), actor)
    assert d20.call_count == damage.call_count == 3
    assert [(s["target_id"], s["roll"]) for s in result["attacks"]] == [(first, 15), (second, 16), (third, 17)]
    assert [s["damage"] for s in result["attacks"]] == [5, 7, 9]
    assert result["damage"] == 21
    state = await warrior.reload()
    assert [participant(state, foe).hp_current for foe in (first, second, third, outside)] == [
        0 if falls else 95,
        93,
        91,
        100,
    ]
    assert combat_spatial.position(combat_spatial.require_spatial(state), actor) == pos(0)
    assert await stamina(actor) == before - 5


@pytest.mark.parametrize(("ability", "skip"), [(WHIRLWIND, False), (WHIRLWIND, True), (CLEAVE, False)])
async def test_second_swing_reloads(warrior: MawlingHarness, ability: str, skip: bool) -> None:
    distances = (2, 3) if ability == CLEAVE else (2, 3, 4, 5) if skip else (2, 3, 4)
    targets = (await battlefield(warrior, ability, distances))[: len(distances)]
    actor = warrior.players[0]
    await favor(warrior)
    await declare(warrior, ability, targets if ability == CLEAVE else [])
    spent = (await stamina(actor)) - (4 if ability == CLEAVE else 5)
    faces = (15, 16) if ability == CLEAVE else (15, 16, 17)
    hit_targets = [pid for i, pid in enumerate(targets) if not (skip and i == 2)]
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(face) for face in faces]) as d20,
        patch("check_resolution_attack.dice_roll", side_effect=[_damage_die(n) for n in (4, 5, 6)]) as damage,
    ):
        first = await warrior.command("resolve_phase", {})
        if ability == CLEAVE:
            await fresh_session(warrior, await warrior.reload())
        second = await warrior.command("resolve_phase", {})
        assert first["fate_offer"]["roller_id"] == second["fate_offer"]["roller_id"] == actor
        saved = await warrior.reload()
        assert saved.ally_continuation and saved.ally_continuation["attack"]["swing_targets"] == targets
        assert [participant(saved, pid).hp_current for pid in targets] == [95, *([100] * (len(targets) - 1))]
        assert d20.call_count == 2 and damage.call_count == 1
        assert await stamina(actor) == spent
        if skip:
            unavailable = participant(saved, targets[2])
            unavailable.is_fallen = True
            unavailable.hp_current = 0
            saved = await warrior.persist()
        await fresh_session(warrior, saved)
        resumed = await warrior.command("resolve_phase", {})
        if ability == WHIRLWIND:
            assert resumed["fate_offer"]["roller_id"] == actor
            wrapped = await warrior.command("resolve_phase", {})
            assert actor not in {packet["actor_id"] for packet in wrapped["packets"]}
            resumed = wrapped["settled_fate"]
        else:
            wrapped = await warrior.command("resolve_phase", {})
            assert actor not in {packet["actor_id"] for packet in wrapped["packets"]}
        result = receipt(resumed["packets"], actor)
        assert d20.call_count == len(faces) and damage.call_count == len(hit_targets)
        assert [s["target_id"] for s in result["attacks"]] == targets
        attacks = [s for s in result["attacks"] if not s.get("skipped")]
        assert [s["roll"] for s in attacks] == ([15, 15] if ability == CLEAVE else list(faces))
        state = await warrior.reload()
        assert [participant(state, pid).hp_current for pid in hit_targets] == [
            100 - n for n in range(5, 5 + len(hit_targets))
        ]
        if skip:
            assert result["attacks"][2]["skipped"] is True
            assert participant(state, targets[2]).hp_current == 0
        await warrior.command("resolve_phase", {}, error=True)
    assert await stamina(actor) == spent


async def test_reload_finishes_the_receipt_for_a_foe_dropped_by_the_pending_swing(warrior: MawlingHarness) -> None:
    actor = warrior.players[0]
    await warrior.pool.execute(
        """UPDATE players SET data = jsonb_set(data, '{equipment,main_hand,critical_save}',
               '{"save":"WIS","dc":10,"applies_condition":"shaken"}')
           WHERE player_id = $1""",
        actor,
    )
    first, second, *_ = await battlefield(warrior, WHIRLWIND, (2, 3))
    state = await warrior.reload()
    participant(state, first).hp_current = 2
    await warrior.persist()
    await favor(warrior)
    await declare(warrior, WHIRLWIND, [])
    before = await stamina(actor)
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(n) for n in (20, 15, 16)]) as d20,
        patch("check_resolution_attack.dice_roll", side_effect=[_damage_die(n) for n in (4, 5, 6)]) as damage,
    ):
        attack = await warrior.command("resolve_phase", {})
        save = await warrior.command("resolve_phase", {})
        assert attack["fate_offer"]["roller_id"] == actor
        assert save["fate_offer"]["roller_id"] == first and save["fate_offer"]["roll_kind"] == "save"
        saved = await warrior.reload()
        assert participant(saved, first).is_fallen
        assert participant(saved, second).hp_current == 100
        assert d20.call_count == damage.call_count == 2
        await fresh_session(warrior, saved)
        assert (await warrior.command("resolve_phase", {}))["fate_offer"]["roller_id"] == actor
        wrapped = await warrior.command("resolve_phase", {})
        result = receipt(wrapped["settled_fate"]["packets"], actor)
    assert [(s["target_id"], s["damage"]) for s in result["attacks"]] == [(first, 10), (second, 7)]
    assert result["attacks"][0]["target_fallen"]
    assert result["attacks"][0]["critical_save"]["roll"] == 15
    assert d20.call_count == damage.call_count == 3
    assert await stamina(actor) == before - 5


async def test_held_swing_finishes_once_when_its_target_falls_during_the_hold(warrior: MawlingHarness) -> None:
    targets = (await battlefield(warrior, WHIRLWIND, (2, 3, 4)))[:3]
    actor = warrior.players[0]
    await favor(warrior)
    await declare(warrior, WHIRLWIND, [])
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(face) for face in (15, 16, 17)]) as d20,
        patch("check_resolution_attack.dice_roll", side_effect=[_damage_die(n) for n in (4, 5, 6)]) as damage,
    ):
        await warrior.command("resolve_phase", {})
        await warrior.command("resolve_phase", {})
        saved = await warrior.reload()
        assert saved.ally_continuation and saved.ally_continuation["attack"]["prepared"]
        held = participant(saved, targets[1])
        held.is_fallen = True
        held.hp_current = 0
        await fresh_session(warrior, await warrior.persist())
        resumed = await warrior.command("resolve_phase", {})
        assert resumed["fate_offer"]["roller_id"] == actor
        assert d20.call_count == 3
        wrapped = await warrior.command("resolve_phase", {})
        result = receipt(wrapped["settled_fate"]["packets"], actor)
    assert [(s["target_id"], s["roll"], s.get("skipped")) for s in result["attacks"]] == [
        (targets[0], 15, None),
        (targets[1], 16, None),
        (targets[2], 17, None),
    ], result
    assert d20.call_count == 3 and damage.call_count == 3
    state = await warrior.reload()
    assert participant(state, targets[2]).hp_current == 93
