import copy
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from combat._catalog_fixtures import LUNGE, deps, hold, setup, wrap
from sample_fixtures import make_context

import combat_hold
from combat_packet import _resolve_one_packet
from combat_phase import advance_combat_phase
from combat_support import _participant_summary
from encounter_roles import derive_role_stats
from session_data import CombatState


async def test_spent_lunge_is_hidden_and_direct_call_writes_nothing():
    state, actor, packet = setup()
    d = deps()
    first = await _resolve_one_packet(make_context().userdata, state, packet, **d)
    assert first["condition_inflicted"] == "grappled"
    assert first["roll"] == 14
    assert "Lunge" not in _participant_summary(actor)["actions"]
    before = state.to_dict()
    calls = d["sink"].emit.call_count
    second = await _resolve_one_packet(make_context().userdata, state, packet, **d)
    assert second["resolved"] is False
    assert state.to_dict() == before
    assert d["resolver"].resolve_attack.call_count == 1
    assert d["sink"].emit.call_count == calls


async def test_spent_lunge_declaration_is_refused():
    state, actor, packet = setup()
    await _resolve_one_packet(make_context().userdata, state, packet, **deps())
    with pytest.raises(ValueError, match="unavailable"):
        advance_combat_phase(
            state, declarations={actor.id: {"type": "attack", "action": "Lunge", "target_id": "player_1"}}
        )


@pytest.mark.parametrize("role,uses", [("standard", 1), ("elite", 2), ("boss", 2)])
async def test_role_enhanced_encounter_budget_is_spent_twice(role, uses):
    action = {**LUNGE, "recharge": {"kind": "encounter", "uses": 1}}
    derived = derive_role_stats({"hp": 10, "action_pool": [action]}, role)
    state, _actor, packet = setup(derived["action_pool"][0])
    d = deps(seed=2)
    for _ in range(uses):
        assert (await _resolve_one_packet(make_context().userdata, state, packet, **d))["resolved"]
    assert not (await _resolve_one_packet(make_context().userdata, state, packet, **d))["resolved"]
    assert d["resolver"].resolve_attack.call_count == uses


def test_minion_strips_lunge_preserves_basic_attack():
    basic = {"name": "Bite", "damage": "1d4", "properties": []}
    derived = derive_role_stats({"hp": 10, "action_pool": [LUNGE, basic]}, "minion")
    assert derived["action_pool"] == [basic]


async def test_spent_lunge_opens_no_reaction_window():
    state, actor, packet = setup()
    d = deps()
    await _resolve_one_packet(make_context().userdata, state, packet, **d)
    player = state.participants[0]
    player.has_reaction_ability = True
    player.reaction_ids = ["skirmisher_sidestep"]
    state.pending_declarations = {actor.id: {"type": "attack", "action": "Lunge", "target_id": player.id}}
    state.held_actions = combat_hold.hold_enemy_packets(state, [SimpleNamespace(actor_id=actor.id, initiative=12)])
    await combat_hold.pump(make_context().userdata, state, packet_deps=d)
    assert state.open_window is None
    assert not state.held_actions
    assert d["resolver"].resolve_attack.call_count == 1


async def test_roll_recharge_four_stays_spent_five_restores_next_round():
    state, _actor, packet = setup()
    await _resolve_one_packet(make_context().userdata, state, packet, **deps())
    with patch("combat_recharge.roll", return_value=SimpleNamespace(total=4)) as roll:
        state = await wrap(state)
        assert "Lunge" not in _participant_summary(state.participants[1])["actions"]
        roll.assert_called_once_with("1d6")
    state = CombatState.from_dict(json.loads(json.dumps(state.to_dict())))
    with patch("combat_recharge.roll", return_value=SimpleNamespace(total=5)) as roll:
        state = await wrap(state)
        assert "Lunge" in _participant_summary(state.participants[1])["actions"]
        roll.assert_called_once_with("1d6")


async def test_recharge_is_once_per_round_across_reload():
    import combat_recharge

    state, _actor, packet = setup()
    await _resolve_one_packet(make_context().userdata, state, packet, **deps())
    state.round_number = 2
    with patch("combat_recharge.roll", return_value=SimpleNamespace(total=4)) as roll:
        combat_recharge.recharge_round(state)
        state = CombatState.from_dict(json.loads(json.dumps(state.to_dict())))
        combat_recharge.recharge_round(state)
        roll.assert_called_once()
        assert "Lunge" not in _participant_summary(state.participants[1])["actions"]


async def test_round_budget_resets_independently_and_encounter_does_not():
    for kind, restored in [("round", True), ("encounter", False)]:
        state, _actor, packet = setup({**LUNGE, "recharge": {"kind": kind, "uses": 1}})
        await _resolve_one_packet(make_context().userdata, state, packet, **deps())
        state = await wrap(state)
        assert ("Lunge" in _participant_summary(state.participants[1])["actions"]) is restored


def test_action_ledger_rejects_duplicate_names():
    _state, actor, _ = setup()
    actor.action_pool.append({**LUNGE, "name": "lunge"})
    with pytest.raises(ValueError, match="duplicate"):
        _participant_summary(actor)


async def test_held_lunge_receipt_resumes_without_roll_or_second_spend():
    state, actor, _ = setup()
    hold(state, actor)
    d = deps()
    session = make_context().userdata
    await combat_hold.pump(session, state, packet_deps=d)
    assert state.open_window is not None
    assert state.open_window["stage"] == "pre_roll"
    await combat_hold.pump(session, state, packet_deps=d)
    assert state.open_window is not None
    assert state.open_window["stage"] == "post_roll"
    assert "Lunge" not in _participant_summary(actor)["actions"]
    state = CombatState.from_dict(json.loads(json.dumps(state.to_dict())))
    result = await combat_hold.pump(session, state, packet_deps=d)
    assert result[0]["roll"] == 14
    assert result[0]["condition_inflicted"] == "grappled"
    assert state.participants[1].action_ledger["lunge"]["remaining"] == 0
    assert d["resolver"].resolve_attack.call_count == 1


async def test_held_receipt_cannot_authorize_other_head_or_direct_packet():
    state, actor, packet = setup()
    hold(state, actor)
    d = deps()
    session = make_context().userdata
    await combat_hold.pump(session, state, packet_deps=d)
    await combat_hold.pump(session, state, packet_deps=d)
    head = state.held_actions[0]
    before = state.to_dict()
    calls = d["sink"].emit.call_count
    foreign = copy.deepcopy(head)
    for provided in [foreign, None]:
        summary = await _resolve_one_packet(session, state, packet, **d, _held_head=provided)
        assert not summary["resolved"]
        assert state.to_dict() == before
        assert d["resolver"].resolve_attack.call_count == 1
        assert d["sink"].emit.call_count == calls
    assert actor.last_action_execution is not None
    actor.last_action_execution = {**actor.last_action_execution, "id": "different-spend"}
    summary = await _resolve_one_packet(session, state, packet, **d, _held_head=head)
    assert not summary["resolved"]
    assert d["resolver"].resolve_attack.call_count == 1
    actor.last_action_execution = head["execution_receipt"]
    foreign["execution_id"] = "another-execution"
    state.held_actions = [foreign]
    before = state.to_dict()
    summary = await _resolve_one_packet(session, state, packet, **d, _held_head=foreign)
    assert not summary["resolved"]
    assert state.to_dict() == before
    assert d["resolver"].resolve_attack.call_count == 1


def test_legacy_participant_defaults_do_not_reset_existing_ledger():
    state, _actor, _packet = setup()
    data = state.to_dict()
    data["participants"][1].pop("action_ledger")
    restored = CombatState.from_dict(data)
    assert _participant_summary(restored.participants[1])["actions"] == ["Lunge"]
    restored.participants[1].action_ledger["lunge"]["remaining"] = 0
    restored = CombatState.from_dict(restored.to_dict())
    assert _participant_summary(restored.participants[1])["actions"] == []


def test_unlimited_attack_stays_available():
    _state, actor, _ = setup({"name": "Bite", "damage": "1d4"})
    assert _participant_summary(actor)["actions"] == ["Bite"]
    assert actor.action_ledger == {}


@pytest.mark.parametrize(
    "entry",
    [
        None,
        {"remaining": -1, "round": 1},
        {"remaining": 2, "round": 1},
        {"remaining": True, "round": 1},
        {"remaining": 0, "round": None},
        {"remaining": 0, "round": 0},
    ],
)
def test_malformed_action_ledger_fails_loud(entry):
    _state, actor, _packet = setup()
    actor.action_ledger = {"lunge": entry}
    with pytest.raises(ValueError, match="malformed action ledger"):
        _participant_summary(actor)


def test_unknown_action_ledger_entry_fails_loud():
    _state, actor, _packet = setup()
    actor.action_ledger = {"foreign": {"remaining": 1, "round": 1}}
    with pytest.raises(ValueError, match="unknown action ledger"):
        _participant_summary(actor)


def test_load_boundary_rejects_duplicate_names():
    from combat_init_validation import validate_enemy_action_shapes

    with pytest.raises(ValueError, match="duplicate"):
        validate_enemy_action_shapes([{"id": "mawling", "action_pool": [LUNGE, {**LUNGE, "name": "lunge"}]}])


async def test_legacy_unrolled_held_action_resumes_with_one_execution_id():
    state, actor, _packet = setup()
    hold(state, actor)
    state.held_actions[0].pop("execution_id")
    state = CombatState.from_dict(json.loads(json.dumps(state.to_dict())))
    d = deps()
    session = make_context().userdata
    await combat_hold.pump(session, state, packet_deps=d)
    await combat_hold.pump(session, state, packet_deps=d)
    execution_id = state.held_actions[0]["execution_id"]
    assert execution_id
    state = CombatState.from_dict(json.loads(json.dumps(state.to_dict())))
    assert state.held_actions[0]["execution_receipt"]["id"] == execution_id
    result = await combat_hold.pump(session, state, packet_deps=d)
    assert result[0]["condition_inflicted"] == "grappled"
    assert state.participants[1].action_ledger["lunge"]["remaining"] == 0
    d["resolver"].resolve_attack.assert_called_once()


@pytest.mark.parametrize("recharge", [None, {"kind": "encounter", "uses": 2}])
async def test_pending_held_execution_refuses_direct_call_even_with_available_uses(recharge):
    action = {**LUNGE}
    if recharge is None:
        action.pop("recharge")
    else:
        action["recharge"] = recharge
    state, actor, packet = setup(action)
    hold(state, actor)
    d = deps()
    session = make_context().userdata
    await combat_hold.pump(session, state, packet_deps=d)
    await combat_hold.pump(session, state, packet_deps=d)
    before = state.to_dict()
    calls = d["sink"].emit.call_count
    summary = await _resolve_one_packet(session, state, packet, **d)
    assert not summary["resolved"]
    assert state.to_dict() == before
    assert d["resolver"].resolve_attack.call_count == 1
    assert d["sink"].emit.call_count == calls
    result = await combat_hold.pump(session, state, packet_deps=d)
    assert result[0]["resolved"]
    assert d["resolver"].resolve_attack.call_count == 1
    if recharge is not None:
        assert actor.action_ledger["lunge"]["remaining"] == 1
