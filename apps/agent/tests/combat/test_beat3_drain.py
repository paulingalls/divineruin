"""Beat 3 drains only the engine failures explicitly declared unresolvable."""

from copy import deepcopy

import pytest
from combat._helpers import _call, _ctx_at_resolution, _resolve_deps

import combat_hold
import combat_turn


async def test_moved_target_ac_drains_with_an_unresolved_summary_and_error_log(caplog):
    ctx = _ctx_at_resolution(enemy_hp=20)
    deps = _resolve_deps(damage=3)
    caplog.set_level("ERROR", logger="divineruin.tools")

    await _call(ctx, deps)
    await _call(ctx, deps)
    await _call(ctx, deps)
    ctx.userdata.combat_state.get_participant("player_1").ac = 16

    result = await _call(ctx, deps)

    reason = (
        "held roll for 'goblin_scout_1' was made against AC 14, but the target's "
        "effective AC is now 16 — the pause changed the roll's premise"
    )
    assert result["packets"] == [{"actor_id": "goblin_scout_1", "resolved": False, "reason": reason}]
    assert ctx.userdata.combat_state.held_actions == []
    matching_logs = [
        record for record in caplog.records if "goblin_scout_1" in record.message and reason in record.message
    ]
    assert len(matching_logs) == 1


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(ValueError("unrelated held resolver value error"), id="unrelated-value-error"),
        pytest.param(RuntimeError("unrelated held resolver runtime error"), id="runtime-error"),
    ],
)
async def test_unrelated_resolver_error_propagates_and_rolls_the_phase_back(monkeypatch, error):
    ctx = _ctx_at_resolution(enemy_hp=20)
    ctx.userdata.combat_state.reactions_available = {}
    deps = _resolve_deps(damage=3)
    await _call(ctx, deps)
    committed = ctx.userdata.combat_state
    committed_hp = committed.get_participant("player_1").hp_current
    committed_queue = deepcopy(committed.held_actions)
    deps["mutations"].save_combat_state.reset_mock()

    async def fail_from_resolver(_session, state, _packet, **_deps):
        state.get_participant("player_1").hp_current = 1
        state.held_actions[0]["opened"].append("injected")
        raise error

    monkeypatch.setattr(combat_hold, "_resolve_one_packet", fail_from_resolver)

    with pytest.raises(type(error)) as raised:
        await combat_turn._resolve_phase_impl(ctx, **deps)

    assert raised.value is error
    assert ctx.userdata.combat_state is committed
    assert committed.get_participant("player_1").hp_current == committed_hp
    assert committed.held_actions == committed_queue
    deps["mutations"].save_combat_state.assert_not_awaited()


async def test_iteration_with_no_pop_unresolved_summary_or_new_window_raises(monkeypatch):
    ctx = _ctx_at_resolution(enemy_hp=20)
    deps = _resolve_deps(damage=3)
    await _call(ctx, deps)
    committed = ctx.userdata.combat_state
    committed_queue = deepcopy(committed.held_actions)
    deps["mutations"].save_combat_state.reset_mock()
    monkeypatch.setattr(combat_hold, "_open", lambda *_args, **_kwargs: None)

    with pytest.raises(RuntimeError, match=r"goblin_scout_1.*made no progress"):
        await combat_turn._resolve_phase_impl(ctx, **deps)

    assert ctx.userdata.combat_state is committed
    assert committed.held_actions == committed_queue
    assert committed.open_window is None
    deps["mutations"].save_combat_state.assert_not_awaited()
