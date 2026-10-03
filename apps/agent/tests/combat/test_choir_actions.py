from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from combat._catalog_fixtures import deps, setup
from sample_fixtures import make_context
from voice_condition_fixtures import spatial_record

from combat_packet import _resolve_one_packet

SCREAM = {
    "name": "Memory Scream",
    "kind": "attack",
    "resolution": "save",
    "damage": "3d8",
    "damage_type": "psychic",
    "save": "WIS",
    "dc": 18,
    "reach": 60,
    "type": "area",
    "save_success_damage": "none",
    "conditions_on_failure": [{"applies_condition": "stunned", "duration": 1}],
    "conditions_on_success": [],
}


@pytest.mark.parametrize("success", [True, False])
async def test_memory_scream_save_negates(success):
    state, actor, packet = setup(SCREAM)
    actor.creature_id = "hollow_choir"
    actor.hp_current = actor.hp_max = 100
    saves = SimpleNamespace(
        success=success,
        save_type="wisdom",
        roll=20 if success else 1,
        total=20 if success else 1,
        dc=18,
        narrative_hint="",
        dramatic=False,
        context="",
        advantage_applied=False,
    )
    d = deps()
    d["concentration_break_mod"].break_concentration_on_incapacitation = AsyncMock(return_value=None)
    with (
        patch("check_resolution_save.roll_participant_save", return_value=saves) as saved,
        patch("combat_enemy_action.dice_roll", return_value=SimpleNamespace(total=12)) as damage_rolls,
    ):
        result = await _resolve_one_packet(make_context().userdata, state, packet, **d)
    assert result["resolved"]
    assert saved.call_count == 2
    assert all(not t["half_on_success"] and not t["damage_halved"] for t in result["targets"])
    assert all(call.args[1:3] == ("WIS", 18) for call in saved.call_args_list)
    assert all(call.args == ("3d8",) for call in damage_rolls.call_args_list)
    assert not d["resolver"].resolve_attack.called
    assert state.participants[0].hp_current == (25 if success else 13)
    assert actor.hp_current == (100 if success else 88)
    for target in state.participants:
        assert any(c["type"] == "stunned" for c in target.conditions) is not success


async def test_silence_fixed_geometry_exact_expiry():
    from combat._catalog_fixtures import wrap

    from combat_state import CombatState

    action = {
        "name": "Silence Void",
        "kind": "silence",
        "radius_ft": 30,
        "rounds": 3,
        "recharge": {"kind": "encounter", "uses": 1},
    }
    state, actor, packet = setup(action)
    actor.creature_id = "hollow_choir"
    result = await _resolve_one_packet(make_context().userdata, state, packet, **deps())
    assert result["resolved"]
    assert len(spatial_record(state)["zones"]) == 1
    assert actor.choir_suppression is not None
    assert actor.choir_suppression["expires_round"] == 3
    spatial_record(state)["positions"][actor.id] = {"x": 100, "y": 0, "z": 0}
    zone = next(iter(spatial_record(state)["zones"].values()))
    assert spatial_record(state)["locations"][zone["center_id"]] == {"x": 0, "y": 0, "z": 0}
    state = CombatState.from_dict(state.to_dict())
    for round_number in (2, 3, 4):
        state = await wrap(state)
        assert state.round_number == round_number
        assert len(spatial_record(state)["zones"]) == 1
    state = await wrap(state)
    assert state.round_number == 5
    assert spatial_record(state)["zones"] == {}
    assert spatial_record(state)["locations"] == {}


@pytest.mark.parametrize("source_x,immobilized", [(100, False), (15, False), (100, True)])
async def test_melody_source_duration_movement(source_x, immobilized):
    from combat_state import CombatState
    from declarations import Declaration, DeclarationType

    action = {
        "name": "Stolen Melody",
        "kind": "charm",
        "save": "WIS",
        "dc": 20,
        "duration_dice": "1d4",
        "movement": "approach_source",
        "recharge": {"kind": "roll", "die": 6, "threshold": 5},
    }
    state, actor, packet = setup(action)
    actor.creature_id = "hollow_choir"
    spatial_record(state)["positions"][actor.id] = {"x": 100, "y": 0, "z": 0}
    with patch("check_resolution_save.roll_participant_save", return_value=SimpleNamespace(success=False)):
        result = await _resolve_one_packet(make_context().userdata, state, packet, **deps())
    assert result["resolved"]
    target = state.participants[0]
    charm = next(c for c in target.conditions if c["type"] == "charmed")
    assert charm["source"] == actor.id and 1 <= charm["duration"] <= 4
    state = CombatState.from_dict(state.to_dict())
    target = state.participants[0]
    spatial_record(state)["positions"][actor.id]["x"] = source_x
    if immobilized:
        target.conditions.append({"type": "restrained"})
    expected_x = 0 if immobilized else min(30, source_x)
    move = Declaration(
        type=DeclarationType.MANEUVER, action="move", target_id=target.id, destination={"x": -30, "y": 0, "z": 0}
    )
    turn = SimpleNamespace(actor_id=target.id, declaration=move)
    result = await _resolve_one_packet(make_context().userdata, state, turn, **deps())
    assert spatial_record(state)["positions"][target.id] == {"x": expected_x, "y": 0, "z": 0}
    state = CombatState.from_dict(state.to_dict())
    result = await _resolve_one_packet(make_context().userdata, state, turn, **deps())
    assert spatial_record(state)["positions"][target.id] == {"x": expected_x, "y": 0, "z": 0}


@pytest.mark.parametrize("success", [True, False])
async def test_cacophony_branch_conditions(success):
    import copy

    from creature_combat_helpers import catalog

    action = copy.deepcopy(next(r for r in catalog() if r["id"] == "hollow_choir")["actives"][1])
    state, actor, packet = setup(action)
    actor.creature_id = "hollow_choir"
    actor.hp_current = actor.hp_max = 100
    save = SimpleNamespace(
        success=success,
        save_type="constitution",
        roll=1,
        total=1,
        dc=18,
        narrative_hint="",
        dramatic=False,
        context="",
        advantage_applied=False,
    )
    d = deps()
    d["concentration_break_mod"].break_concentration_on_incapacitation = AsyncMock(return_value=None)
    with (
        patch("check_resolution_save.roll_participant_save", return_value=save),
        patch("combat_enemy_action.dice_roll", return_value=SimpleNamespace(total=12)),
    ):
        result = await _resolve_one_packet(make_context().userdata, state, packet, **d)
    assert result["resolved"] and not d["resolver"].resolve_attack.called
    for target, hp in [(actor, 100), (state.participants[0], 25)]:
        assert target.hp_current == hp - (6 if success else 12)
        assert {c["type"] for c in target.conditions} == ({"deafened"} if success else {"deafened", "stunned"})
        assert next(c for c in target.conditions if c["type"] == "deafened")["duration"] == 10


@pytest.mark.parametrize("distance,included", [(59, True), (60, True), (61, False)])
async def test_choir_range_target_boundaries(distance, included):
    state, actor, packet = setup(SCREAM)
    actor.creature_id = "hollow_choir"
    actor.hp_current = 100
    spatial_record(state)["positions"][state.participants[0].id] = {"x": distance, "y": 0, "z": 0}
    d = deps()
    d["concentration_break_mod"].break_concentration_on_incapacitation = AsyncMock(return_value=None)
    save = SimpleNamespace(
        success=False,
        save_type="wisdom",
        roll=1,
        total=1,
        dc=18,
        narrative_hint="",
        dramatic=False,
        context="",
        advantage_applied=False,
    )
    with (
        patch("check_resolution_save.roll_participant_save", return_value=save),
        patch("combat_enemy_action.dice_roll", return_value=SimpleNamespace(total=12)),
    ):
        await _resolve_one_packet(make_context().userdata, state, packet, **d)
    assert state.participants[0].hp_current == (13 if included else 25)
    assert actor.hp_current == 88


@pytest.mark.parametrize("hit,success", [(False, False), (True, True), (True, False)])
async def test_dissonant_hit_then_save(hit, success):
    from combat.test_combined_actions import _attack_result
    from creature_combat_helpers import catalog

    action = next(r for r in catalog() if r["id"] == "hollow_choir")["attacks"][1]
    state, actor, packet = setup(action)
    actor.creature_id = "hollow_choir"
    d = deps()
    d["resolver"].resolve_attack.side_effect = None
    d["resolver"].resolve_attack.return_value = _attack_result(hit=hit)
    save = SimpleNamespace(success=success, save_type="constitution", roll=1, total=1, dc=18, advantage_applied=False)
    with patch("check_resolution_save.roll_participant_save", return_value=save) as rolls:
        await _resolve_one_packet(make_context().userdata, state, packet, **d)
    assert rolls.call_count == int(hit)
    conditions = state.participants[0].conditions
    assert bool(conditions) == (hit and not success)
    if conditions:
        assert conditions[0]["type"] == "deafened" and conditions[0]["duration"] == 10


@pytest.mark.parametrize(
    "immune,damage,source", [(True, 0, "choir"), (False, 1, "choir"), (False, 0, "choir"), (False, 1, "other")]
)
async def test_melody_movement_requires_landed_live_charm(immune, damage, source):
    from creature_combat_helpers import catalog

    from choir_effects import approach
    from condition_sources import clear_charm_from_damage

    action = next(r for r in catalog() if r["id"] == "hollow_choir")["actives"][0]
    state, actor, packet = setup(action)
    actor.creature_id = "hollow_choir"
    spatial_record(state)["positions"][actor.id] = {"x": 100, "y": 0, "z": 0}
    target = state.participants[0]
    if immune:
        target.condition_immunities["charmed"] = "test immunity"
    with patch("check_resolution_save.roll_participant_save", return_value=SimpleNamespace(success=False)):
        await _resolve_one_packet(make_context().userdata, state, packet, **deps())
    target.conditions = clear_charm_from_damage(target.conditions, actor.id if source == "choir" else "other", damage)
    approach(state, target)
    assert spatial_record(state)["positions"][target.id]["x"] == (0 if immune or (damage and source == "choir") else 30)


async def test_suppression_before_roll_spend():
    from choir_effects import advance_round, exposure
    from combat_action_availability import action_summary
    from combat_state import CombatState

    state, actor, packet = setup(SCREAM)
    actor.creature_id = "hollow_choir"
    spatial_record(state)["zones"]["test"] = {"kind": "silence", "center_id": actor.id, "radius_ft": 30}
    exposure(state)
    assert actor.choir_suppression == {"expires_round": 3, "active": True}
    for _ in range(2):
        assert action_summary(actor)["executable_actions"][0]["available"] is False
        state = CombatState.from_dict(state.to_dict())
        actor = state.participants[1]
        exposure(state)
        assert actor.choir_suppression is not None
        assert actor.choir_suppression["expires_round"] == 3
    d = deps()
    d["concentration_break_mod"].break_concentration_on_incapacitation = AsyncMock(return_value=None)
    result = await _resolve_one_packet(make_context().userdata, state, packet, **d)
    assert result["resolved"] is False and not d["resolver"].resolve_attack.called
    zone = spatial_record(state)["zones"].pop("test")
    exposure(state)
    assert actor.choir_silence_exposed is False
    assert not action_summary(actor)["executable_actions"][0]["available"]
    assert not (await _resolve_one_packet(make_context().userdata, state, packet, **d))["resolved"]
    spatial_record(state)["zones"]["test"] = zone
    exposure(state)
    state.round_number = 3
    advance_round(state)
    assert actor.choir_suppression is not None
    assert actor.choir_suppression["active"] is False
    exposure(state)
    assert actor.choir_suppression == {"expires_round": 3, "active": False}
    assert not action_summary(actor)["executable_actions"][0]["available"]
    del spatial_record(state)["zones"]["test"]
    exposure(state)
    assert action_summary(actor)["executable_actions"][0]["available"]
    spatial_record(state)["zones"]["test"] = {"kind": "silence", "center_id": actor.id, "radius_ft": 30}
    exposure(state)
    assert actor.choir_suppression == {"expires_round": 5, "active": True}


async def test_runtime_effect_roundtrip_validation():
    import copy

    from choir_effects import inflict_silence
    from combat_state import CombatState

    state, actor, packet = setup(SCREAM)
    actor.creature_id = "hollow_choir"
    inflict_silence(state, actor, {"radius_ft": 30, "rounds": 3}, packet.declaration)
    data = state.to_dict()
    assert CombatState.from_dict(data).to_dict() == data
    changed = copy.deepcopy(data)
    changed.pop("choir_silences")
    with pytest.raises(ValueError, match="expiry owner"):
        CombatState.from_dict(changed)
    zone_id = next(iter(data["choir_silences"]))
    for field, value in [
        ("expires_round", 4),
        ("expires_round", True),
        ("source_id", "missing"),
        ("center_id", "missing"),
    ]:
        changed = copy.deepcopy(data)
        changed["choir_silences"][zone_id][field] = value
        with pytest.raises(ValueError):
            CombatState.from_dict(changed)
    changed = copy.deepcopy(data)
    changed["participants"][1]["choir_suppression"]["active"] = False
    with pytest.raises(ValueError):
        CombatState.from_dict(changed)


async def test_melody_movement_stops_at_charm_expiry():
    from combat._catalog_fixtures import wrap
    from creature_combat_helpers import catalog

    from choir_effects import approach
    from combat_state import CombatState

    action = next(r for r in catalog() if r["id"] == "hollow_choir")["actives"][0]
    state, actor, packet = setup(action)
    actor.creature_id = "hollow_choir"
    spatial_record(state)["positions"][actor.id] = {"x": 100, "y": 0, "z": 0}
    with (
        patch("check_resolution_save.roll_participant_save", return_value=SimpleNamespace(success=False)),
        patch("dice.roll", return_value=SimpleNamespace(total=1)),
    ):
        await _resolve_one_packet(make_context().userdata, state, packet, **deps())
    state = await wrap(state)
    target = state.participants[0]
    forced = approach(state, target)
    assert forced is not None and forced["moved_ft"] == 30
    state = await wrap(state)
    state = CombatState.from_dict(state.to_dict())
    assert not state.participants[0].conditions
    assert approach(state, state.participants[0]) is None
    assert spatial_record(state)["positions"][state.participants[0].id]["x"] == 30


def test_melody_replacement_removes_subordinate_movement():
    import conditions
    from choir_effects import approach

    state, actor, _ = setup(SCREAM)
    target = state.participants[0]
    target.conditions = [{"type": "charmed", "duration": 4, "source": actor.id, "choir_melody": True}]
    target.conditions = conditions.apply_condition(target.conditions, "charmed", source=actor.id, duration=2)
    assert approach(state, target) is None
    assert "choir_melody" not in target.conditions[0]


@pytest.mark.parametrize("face,recharged", [(4, False), (5, True), (6, True)])
async def test_melody_recharge_hold_reload(face, recharged):
    from creature_combat_helpers import catalog

    import combat_recharge
    from combat_state import CombatState

    action = next(r for r in catalog() if r["id"] == "hollow_choir")["actives"][0]
    state, actor, packet = setup(action)
    actor.creature_id = "hollow_choir"
    with (
        patch("check_resolution_save.roll_participant_save", return_value=SimpleNamespace(success=True)) as save,
        patch("dice.roll") as duration,
    ):
        assert (await _resolve_one_packet(make_context().userdata, state, packet, **deps()))["resolved"]
        assert save.call_count == 1 and not duration.called
        state = CombatState.from_dict(state.to_dict())
        assert not (await _resolve_one_packet(make_context().userdata, state, packet, **deps()))["resolved"]
        assert save.call_count == 1
    actor = state.participants[1]
    assert actor.action_ledger["stolen melody"]["remaining"] == 0
    with patch("combat_recharge.roll", return_value=SimpleNamespace(total=face)) as recharge:
        combat_recharge.recharge_round(state)
        assert not recharge.called
        state.round_number += 1
        combat_recharge.recharge_round(state)
        combat_recharge.recharge_round(state)
        assert recharge.call_count == 1
    assert combat_recharge.available(actor, action) is recharged


@pytest.mark.parametrize("kind", ["defend", "attack"])
async def test_melody_pending_move_single_speed(kind):
    import copy

    from combat_spatial_declarations import preflight
    from combat_state import CombatState
    from declarations import Declaration, DeclarationType

    state, actor, _ = setup(SCREAM)
    target = state.participants[0]
    other = copy.deepcopy(actor)
    other.id = "other"
    state.participants.append(other)
    spatial_record(state)["positions"][other.id] = {"x": 0, "y": 0, "z": 0}
    spatial_record(state)["speeds"][other.id] = 30
    spatial_record(state)["positions"][actor.id] = {"x": 100, "y": 0, "z": 0}
    target.conditions = [{"type": "charmed", "duration": 4, "source": actor.id, "choir_melody": True}]
    declaration = Declaration(
        type=DeclarationType(kind),
        action=target.action_pool[0]["name"] if kind == "attack" else None,
        target_id=other.id if kind == "attack" else None,
        ac_bonus=2 if kind == "defend" else 0,
    )
    result = await _resolve_one_packet(
        make_context().userdata, state, SimpleNamespace(actor_id=target.id, declaration=declaration), **deps()
    )
    assert result["resolved"]
    if kind == "defend":
        assert result["declaration_type"] == kind and result["ac_bonus"] == 2
    else:
        assert "hit" in result
    assert spatial_record(state)["positions"][target.id]["x"] == 30
    state = CombatState.from_dict(state.to_dict())
    move = Declaration(
        type=DeclarationType.MANEUVER, action="move", target_id=target.id, destination={"x": -30, "y": 0, "z": 0}
    )
    state.participants[0].conditions = []
    preflight(state, [(target.id, move)])
    await _resolve_one_packet(
        make_context().userdata, state, SimpleNamespace(actor_id=target.id, declaration=move), **deps()
    )
    assert spatial_record(state)["positions"][target.id]["x"] == 30


@pytest.mark.parametrize("damage,same_source", [(0, True), (1, True), (1, False)])
async def test_melody_source_damage_owner_clears_movement(damage, same_source):
    import copy

    from choir_effects import approach
    from combat_support import SaveDamageResult, apply_attack_result

    state, actor, _packet = setup(SCREAM)
    target = state.participants[0]
    spatial_record(state)["positions"][actor.id] = {"x": 100, "y": 0, "z": 0}
    target.conditions = [{"type": "charmed", "duration": 4, "source": actor.id, "choir_melody": True}]
    if not same_source:
        actor = copy.deepcopy(actor)
        actor.id = "other"
        state.participants.append(actor)
        spatial_record(state)["positions"][actor.id] = {"x": 0, "y": 0, "z": 0}
        spatial_record(state)["speeds"][actor.id] = 30
    d = deps()
    d.pop("resolver")
    result = SaveDamageResult(
        save_type="wisdom",
        save_success=False,
        damage=damage,
        damage_type="psychic",
        narrative_hint="",
        dramatic=False,
        context="",
    )
    await apply_attack_result(
        make_context().userdata,
        actor,
        SCREAM,
        target,
        result,
        18,
        combat_state=state,
        conn=None,
        publish_roll=False,
        **d,
    )
    forced = approach(state, target)
    assert (forced is None) == (damage > 0 and same_source)


@pytest.mark.parametrize("duration", [1, 4, 10])
async def test_authored_condition_committed_round_clock(duration):
    from combat._catalog_fixtures import wrap

    from combat_condition_landing import _land_condition_on_one
    from combat_state import CombatState

    state, actor, _ = setup(SCREAM)
    condition = "deafened" if duration == 10 else "charmed"
    target = state.participants[0]
    assert _land_condition_on_one(state, target.id, actor, condition, actor.id, duration=duration, packet={})
    state = await wrap(state)
    assert state.participants[0].conditions[0]["duration"] == duration
    for remaining in range(duration - 1, -1, -1):
        state = await wrap(state)
        state = CombatState.from_dict(state.to_dict())
        active = state.participants[0].conditions
        assert bool(active) == bool(remaining)
        if active:
            assert active[0]["duration"] == remaining
