from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from combat._catalog_fixtures import deps, setup
from creature_combat_helpers import catalog, participant
from sample_fixtures import make_context
from voice_condition_fixtures import spatial_record

from combat_packet import _resolve_one_packet
from combat_state import CombatState
from creature_combat import translate_creature
from declarations import Declaration, DeclarationType


def boss_state():
    row = deepcopy(next(r for r in catalog() if r["id"] == "hollow_veilrender"))
    state, _, packet = setup()
    boss = participant(translate_creature(row, encounter_id="test", enemy_id=packet.actor_id, role="standard"))
    state.participants[1] = boss
    return state, boss, row


def save(success=False):
    return SimpleNamespace(
        success=success,
        save_type="constitution",
        roll=10,
        total=10,
        dc=16,
        narrative_hint="",
        dramatic=False,
        context="",
        advantage_applied=False,
    )


def defend(actor):
    return SimpleNamespace(actor_id=actor.id, declaration=Declaration(type=DeclarationType.DEFEND))


@pytest.mark.parametrize("kind", ["player", "companion", "enemy", "temporary_hollowed"])
@pytest.mark.parametrize(
    "distance,success,alive", [(60, False, True), (60, True, True), (61, False, True), (60, False, False)]
)
async def test_field_turn_start_targets(kind, distance, success, alive):
    state, boss, _ = boss_state()
    target = state.participants[0]
    target.type = kind
    boss.hp_current = 120 if alive else 0
    spatial_record(state)["positions"][target.id]["x"] = distance
    expected = alive and distance <= 60 and kind != "temporary_hollowed"
    with (
        patch("check_resolution_save.roll_participant_save", return_value=save(success)) as saves,
        patch("dice.roll", return_value=SimpleNamespace(total=3)) as rolls,
    ):
        result = await _resolve_one_packet(make_context().userdata, state, defend(target), **deps())
    assert saves.call_count == int(expected)
    assert target.hp_current == 25 - (3 if expected and not success else 0)
    if expected:
        assert saves.call_args.args[1:3] == ("CON", 14)
        assert bool(result["turn_start_effects"])
    if expected and not success:
        rolls.assert_called_once_with("1d4")


@pytest.mark.parametrize(
    "name,radius,damage,condition", [("Reality Crush", 20, "4d8", "prone"), ("Corruption Pulse", 60, "3d6", "hollowed")]
)
@pytest.mark.parametrize("success", [False, True])
async def test_area_actions(name, radius, damage, condition, success):
    state, boss, _ = boss_state()
    target = state.participants[0]
    # Hollow recipients are spared by the field, but not by either active.
    target.hollow = {"corruption_aura": 0, "resonance_on_death": 0}
    spatial_record(state)["positions"][target.id]["x"] = radius
    from dataclasses import replace

    enemy = replace(target, id="field_enemy", type="enemy", hollow=None, conditions=[])
    outside = replace(target, id="outside", conditions=[])
    state.participants.extend([enemy, outside])
    for actor, x in ((enemy, radius), (outside, radius + 1)):
        state.initiative_order.append(actor.id)
        spatial_record(state)["positions"][actor.id] = {"x": x, "y": 0, "z": 0}
        spatial_record(state)["speeds"][actor.id] = 30
    action = next(a for a in boss.action_pool if a["name"] == name)
    packet = SimpleNamespace(
        actor_id=boss.id, declaration=Declaration(type=DeclarationType.ATTACK, action=name, target_id=target.id)
    )
    with (
        patch("ward_resolution.resolve_scope_ward", return_value=None),
        patch("check_resolution_save.roll_participant_save", return_value=save(success)) as saves,
        patch("combat_enemy_action.dice_roll", return_value=SimpleNamespace(total=12)) as rolls,
    ):
        result = await _resolve_one_packet(make_context().userdata, state, packet, **deps())
    assert result["resolved"] and len(result["targets"]) == 2
    assert saves.call_args.args[1:3] == (action["save"], 16)
    assert saves.call_count == rolls.call_count == 2
    assert all(call.args == (damage,) for call in rolls.call_args_list)
    assert enemy.hp_current == (19 if success else 13)
    assert outside.hp_current == 25 and outside.conditions == []
    assert target.hp_current == (19 if success else 13)
    assert boss.hp_current == 120
    assert any(c["type"] == condition for c in target.conditions) is not success
    if condition == "hollowed" and not success:
        assert next(c for c in target.conditions if c["type"] == condition)["stage"] == 1


@pytest.mark.parametrize("initial", [80, 115])
async def test_regeneration_and_radiant_receipt_reload(initial):
    state, boss, row = boss_state()
    boss.hp_current = initial
    healed = min(120, initial + 10)
    session = make_context().userdata
    with patch("ward_resolution.resolve_scope_ward", return_value=None):
        first = await _resolve_one_packet(session, state, defend(boss), **deps())
        assert boss.hp_current == healed
        assert row["regeneration"]["narration_cue"] in str(first)
        state = CombatState.from_dict(state.to_dict())
        boss = state.participants[1]
        await _resolve_one_packet(session, state, defend(boss), **deps())
        assert boss.hp_current == healed
        boss.radiant_suppression_pending = True
        state.round_number += 1
        suppressed = await _resolve_one_packet(session, state, defend(boss), **deps())
        assert boss.hp_current == healed and not boss.radiant_suppression_pending
        assert row["regeneration"]["suppressed_cue"] in str(suppressed)
        state.round_number += 1
        resumed = await _resolve_one_packet(session, state, defend(boss), **deps())
        assert boss.hp_current == min(120, healed + 10)
        assert row["regeneration"]["resumed_cue"] in str(resumed)


async def test_field_catalog_boundary_stunned_and_hollow():
    state, boss, row = boss_state()
    target = state.participants[0]
    row["hollow"]["corruption_aura"] = 17
    row["corruption_field"]["dc"] = 19
    boss = participant(translate_creature(row, encounter_id="test", enemy_id=boss.id, role="standard"))
    state.participants[1] = boss
    assert boss.hollow is not None and boss.corruption_field is not None
    target.conditions = [{"type": "stunned", "duration": 1}]
    spatial_record(state)["positions"][target.id]["x"] = 17
    with (
        patch("check_resolution_save.roll_participant_save", return_value=save()) as saves,
        patch("dice.roll", return_value=SimpleNamespace(total=2)),
    ):
        result = await _resolve_one_packet(make_context().userdata, state, defend(target), **deps())
        assert saves.call_args.args[1:3] == ("CON", 19)
        assert not result["resolved"] and target.hp_current == 23
        state.round_number += 1
        spatial_record(state)["positions"][target.id]["x"] = 18
        await _resolve_one_packet(make_context().userdata, state, defend(target), **deps())
        target.hollow = {"corruption_aura": 0, "resonance_on_death": 0}
        state.round_number += 1
        spatial_record(state)["positions"][target.id]["x"] = 0
        await _resolve_one_packet(make_context().userdata, state, defend(target), **deps())
        assert saves.call_count == 1


async def test_field_once_across_hold_reload(dev_db_pool):
    from combat._catalog_fixtures import hold

    import combat_hold

    state, boss, _ = boss_state()
    # A non-Hollow enemy's held turn is exposed to the field too.
    from dataclasses import replace

    victim = replace(
        boss, id="non_hollow_enemy", creature_id="bandit", hollow=None, regeneration=None, corruption_field=None
    )
    state.participants.append(victim)
    state.initiative_order.append(victim.id)
    spatial_record(state)["positions"][victim.id] = {"x": 0, "y": 0, "z": 0}
    spatial_record(state)["speeds"][victim.id] = 30
    hold(state, victim)
    session = make_context().userdata
    with (
        patch("check_resolution_save.roll_participant_save", return_value=save()) as saves,
        patch("dice.roll", return_value=SimpleNamespace(total=3)),
    ):
        summaries = await combat_hold.pump(session, state, packet_deps=deps())
        assert state.open_window is not None and victim.hp_current == 117
        assert "corruption_field" in str(summaries)
        import db_mutations

        await db_mutations.save_combat_state(state.combat_id, state.to_dict(), conn=dev_db_pool)
        loaded = await db_mutations.load_combat_state(state.combat_id, conn=dev_db_pool)
        assert loaded is not None
        state = loaded
        await db_mutations.delete_combat_state(state.combat_id, conn=dev_db_pool)
        await combat_hold.pump(session, state, packet_deps=deps())
        assert saves.call_count == 1
        state.round_number += 1
        await _resolve_one_packet(session, state, defend(state.participants[-1]), **deps())
        assert saves.call_count == 2


@pytest.mark.parametrize("mode", ["encounter", "location"])
async def test_ward_suppression_each_turn(mode, dev_db_pool):
    state, boss, row = boss_state()
    boss.hp_current = 80
    boss.radiant_suppression_pending = True
    if mode == "encounter":
        state.veil_ward = {"active": True}
    import db_mutations
    import db_mutations_veil_ward
    from veil_ward import WardScope

    session = make_context().userdata
    session.location_id = "veilrender_ward_test"
    scope = WardScope.location(session.location_id)
    if mode == "location":
        await db_mutations_veil_ward.write_ward(scope, "cleric", None, dismissible=True, conn=dev_db_pool)
    d = deps()
    d["conn"] = dev_db_pool
    try:
        for _ in range(2):
            result = await _resolve_one_packet(session, state, defend(boss), **d)
            assert result["turn_start_effects"][0]["suppressed"]
            assert boss.hp_current == 80 and not boss.radiant_suppression_pending
            await db_mutations.save_combat_state(state.combat_id, state.to_dict(), conn=dev_db_pool)
            loaded = await db_mutations.load_combat_state(state.combat_id, conn=dev_db_pool)
            assert loaded is not None
            state = loaded
            boss = state.participants[1]
            state.round_number += 1
        state.veil_ward = None
        await db_mutations_veil_ward.dismiss_ward(scope, conn=dev_db_pool)
        result = await _resolve_one_packet(session, state, defend(boss), **d)
        assert boss.hp_current == 90
        assert row["regeneration"]["resumed_cue"] in str(result)
    finally:
        await db_mutations.delete_combat_state(state.combat_id, conn=dev_db_pool)
        await db_mutations_veil_ward.dismiss_ward(scope, conn=dev_db_pool)


@pytest.mark.parametrize(
    "kind,immune,positive",
    [
        ("main", False, True),
        ("bonus", False, True),
        ("rider", False, True),
        ("mixed", False, True),
        ("main", True, False),
        ("zero", False, False),
        ("nonradiant", False, False),
        ("miss", False, False),
    ],
)
async def test_landed_radiant_marks_suppression(kind, immune, positive):
    from dataclasses import replace

    from combat.test_combined_actions import _attack_result

    from combat_support import AutomaticDamageResult, apply_attack_result

    state, boss, _ = boss_state()
    boss.hp_current = 80
    if immune:
        boss.damage_affinities = {"immune": ["radiant"]}
    action: dict = {"name": "test"}
    result = replace(_attack_result(hit=kind != "miss"), damage_type="radiant" if kind in ("main", "miss") else "force")
    if kind in ("bonus", "rider"):
        result = replace(result, **{f"{kind}_damage": 2, f"{kind}_damage_type": "radiant"})
    if kind == "mixed":
        action["damage_components"] = [{"damage": 2, "damage_type": "radiant"}, {"damage": 2, "damage_type": "force"}]
        result = AutomaticDamageResult(4, "force")
    if kind == "zero":
        result = AutomaticDamageResult(0, "radiant")
    d = deps()
    d.pop("resolver")
    await apply_attack_result(
        make_context().userdata,
        state.participants[0],
        action,
        boss,
        result,
        boss.ac,
        combat_state=state,
        publish_roll=False,
        **d,
    )
    assert boss.radiant_suppression_pending is positive


async def test_pulse_no_escalation_spend_and_crush_recharge():
    import combat_recharge
    from combat_action_availability import available_actions

    state, boss, _ = boss_state()
    target = state.participants[0]
    target.hollow = {"corruption_aura": 0, "resonance_on_death": 0}
    target.conditions = [{"type": "hollowed", "stage": 1, "duration": None}]
    target.hp_current = target.hp_max = 100
    with (
        patch("ward_resolution.resolve_scope_ward", return_value=None),
        patch("check_resolution_save.roll_participant_save", return_value=save()),
        patch("combat_enemy_action.dice_roll", return_value=SimpleNamespace(total=12)),
    ):
        for name in ("Corruption Pulse", "Reality Crush"):
            packet = SimpleNamespace(
                actor_id=boss.id, declaration=Declaration(type=DeclarationType.ATTACK, action=name, target_id=target.id)
            )
            result = await _resolve_one_packet(make_context().userdata, state, packet, **deps())
            assert result["resolved"]
        assert next(c for c in target.conditions if c["type"] == "hollowed")["stage"] == 1
    state = CombatState.from_dict(state.to_dict())
    boss = state.participants[1]
    for face, expected in ((4, False), (5, True)):
        state.round_number += 1
        with patch("combat_recharge.roll", return_value=SimpleNamespace(total=face)):
            combat_recharge.recharge_round(state)
        names = [a["name"] for a in available_actions(boss)]
        assert ("Reality Crush" in names) is expected
        assert "Corruption Pulse" not in names


@pytest.mark.parametrize("start,end,damaged", [(30, 61, True), (61, 30, False)])
async def test_field_uses_turn_start_position(start, end, damaged):
    state, _, _ = boss_state()
    target = state.participants[0]
    spatial_record(state)["positions"][target.id]["x"] = start
    spatial_record(state)["speeds"][target.id] = 40
    packet = SimpleNamespace(
        actor_id=target.id,
        declaration=Declaration(
            type=DeclarationType.MANEUVER, action="move", target_id=target.id, destination={"x": end, "y": 0, "z": 0}
        ),
    )
    with (
        patch("check_resolution_save.roll_participant_save", return_value=save()) as saves,
        patch("dice.roll", return_value=SimpleNamespace(total=2)),
    ):
        await _resolve_one_packet(make_context().userdata, state, packet, **deps())
    assert saves.call_count == int(damaged)
    assert target.hp_current == (23 if damaged else 25)
    assert spatial_record(state)["positions"][target.id]["x"] == end


@pytest.mark.parametrize("dead", [False, True])
async def test_destroyed_veilrender_does_not_regenerate(dead):
    state, boss, _ = boss_state()
    boss.hp_current = 0
    boss.is_dead = dead
    await _resolve_one_packet(make_context().userdata, state, defend(boss), **deps())
    assert boss.hp_current == 0 and boss.veilrender_turn_round is None
