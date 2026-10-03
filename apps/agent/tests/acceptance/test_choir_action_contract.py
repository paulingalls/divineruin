import copy
import json
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _resolve_round
from acceptance.test_catalog_action_runtime import runtime as runtime

import combat_turn
import db_mutations
from declaration_payloads import AbilityDecl, DefendDecl
from spell_voice_rules import is_silenced


async def choir(runtime):
    return await runtime("hollow_choir", None)


async def declare_silence(ctx, pid, eid):
    result = json.loads(
        await combat_turn.declare_phase(
            ctx,
            [
                DefendDecl(kind="defend", actor_id=pid),
                AbilityDecl(kind="ability", actor_id=eid, action="Silence Void", targets=[pid], argument_type=""),
            ],
        )
    )
    roster = next(p for p in result["participants"] if p["id"] == eid)
    action = next(a for a in roster["executable_actions"] if a["id"] == "Silence Void")
    assert action["available"] and action["declaration_type"] == "ability"
    return result


async def reload(ctx):
    state = await db_mutations.load_combat_state(ctx.userdata.combat_state.combat_id)
    assert state is not None
    assert state.to_dict() == ctx.userdata.combat_state.to_dict()
    ctx.userdata.combat_state = state
    return state


async def test_silence_production_expiry_transaction_rollback(runtime):
    ctx, pid, eid = await choir(runtime)
    await declare_silence(ctx, pid, eid)
    before = copy.deepcopy(ctx.userdata.combat_state.to_dict())
    emitted = ctx.userdata.room.local_participant.publish_data.call_count
    original = db_mutations.save_combat_state

    async def fail_after_write(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("injected silence persistence failure")

    with patch("db_mutations.save_combat_state", side_effect=fail_after_write):
        with pytest.raises(RuntimeError, match="injected silence persistence failure"):
            await _resolve_round(ctx)
    assert ctx.userdata.combat_state.to_dict() == before
    assert (await reload(ctx)).to_dict() == before
    assert ctx.userdata.room.local_participant.publish_data.call_count == emitted
    await _resolve_round(ctx)
    state = await reload(ctx)
    assert state.round_number == 2 and is_silenced(state, pid)
    actor = state.get_participant(eid)
    assert actor is not None
    assert actor.action_ledger["silence void"]["remaining"] == 0
    effect = next(iter(state.choir_silences.values()))
    assert effect["expires_round"] == 5
    for round_number in (3, 4):
        await combat_turn.declare_phase(ctx, [DefendDecl(kind="defend", actor_id=pid)])
        await _resolve_round(ctx)
        state = await reload(ctx)
        assert state.round_number == round_number and is_silenced(state, pid)
    await combat_turn.declare_phase(ctx, [DefendDecl(kind="defend", actor_id=pid)])
    before = copy.deepcopy(ctx.userdata.combat_state.to_dict())
    with patch("db_mutations.save_combat_state", side_effect=fail_after_write):
        with pytest.raises(RuntimeError, match="injected silence persistence failure"):
            await _resolve_round(ctx)
    assert (await reload(ctx)).to_dict() == before
    assert is_silenced(ctx.userdata.combat_state, pid)
    await _resolve_round(ctx)
    state = await reload(ctx)
    assert state.round_number == 5 and not is_silenced(state, pid)
    assert state.spatial is not None
    assert state.choir_silences == {} and state.spatial["locations"] == {}


@pytest.mark.parametrize("success", [False, True])
async def test_shield_real_cast_transaction_replay(runtime, success):
    from types import SimpleNamespace

    from acceptance.seeds import seed_player_with_pools

    import db
    import db_queries
    import spell_casting

    ctx, pid, eid = await choir(runtime)
    pool = await db.get_pool()
    await seed_player_with_pools(pool, player_id=pid, class_="cleric", known_spells=("divine_bless",))
    import choir_encounter

    facts = choir_encounter.facts(ctx.userdata.combat_state)
    assert facts is not None
    action = facts["search_actions"][1]
    await combat_turn._declare_phase_impl(ctx, {pid: action, eid: {"type": "defend"}})
    with patch("check_resolution.dice_roll", return_value=_d20(20)):
        await _resolve_round(ctx)
    await combat_turn.declare_phase(
        ctx, [AbilityDecl(kind="ability", actor_id=pid, action="divine_bless", targets=[eid], argument_type="")]
    )
    before = copy.deepcopy(ctx.userdata.combat_state.to_dict())
    player_before = await db_queries.get_player(pid)
    original = db_mutations.save_combat_state

    async def fail_after_write(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("injected Shield save failure")

    with (
        patch("check_resolution_save.roll_participant_save", return_value=SimpleNamespace(success=success)),
        patch("db_mutations.save_combat_state", side_effect=fail_after_write),
    ):
        with pytest.raises(RuntimeError, match="injected Shield save failure"):
            await _resolve_round(ctx)
    assert (await reload(ctx)).to_dict() == before
    assert await db_queries.get_player(pid) == player_before
    with (
        patch("check_resolution_save.roll_participant_save", return_value=SimpleNamespace(success=success)) as saves,
        patch("spell_casting._resolve_cast", wraps=spell_casting._resolve_cast) as casts,
    ):
        result = await _resolve_round(ctx)
    assert casts.call_count == 1
    assert sum(call.args[2] == 16 for call in saves.call_args_list) == 1
    assert sum(call.args[2] == 15 for call in saves.call_args_list) == 1
    state = await reload(ctx)
    target_id = eid if success else pid
    assert result["packets"][0]["cast"]["target_id"] == target_id
    assert next(p for p in state.participants if p.id == target_id).conditions[0]["type"] == "blessed"
    player_after = await db_queries.get_player(pid)
    assert player_before is not None and player_after is not None
    assert player_after["focus"]["current"] == player_before["focus"]["current"] - 2


async def test_choir_public_actions_hold_reload(runtime):
    from types import SimpleNamespace

    from acceptance.seeds import seed_player_with_pools

    import db
    from combat_init import class_reaction_ids

    ctx, pid, eid = await choir(runtime)
    pool = await db.get_pool()
    await seed_player_with_pools(pool, player_id=pid, class_="skirmisher")
    player = ctx.userdata.combat_state.get_participant(pid)
    assert player is not None
    player.reaction_ids = class_reaction_ids("skirmisher", player.level)
    assert player.reaction_ids
    player.has_reaction_ability = True
    await combat_turn.declare_phase(
        ctx,
        [
            DefendDecl(kind="defend", actor_id=pid),
            AbilityDecl(kind="ability", actor_id=eid, action="Stolen Melody", targets=[pid], argument_type=""),
        ],
    )
    with (
        patch("check_resolution_save.roll_participant_save", return_value=SimpleNamespace(success=False)) as saves,
        patch("combat_recharge.roll", return_value=SimpleNamespace(total=4)),
    ):
        raw = await combat_turn._resolve_phase_impl(ctx)
        assert isinstance(raw, str)
        response = json.loads(raw)
        if response["next"]["waiting_on"] is None:
            raw = await combat_turn._resolve_phase_impl(ctx)
            assert isinstance(raw, str)
            response = json.loads(raw)
        assert response["next"]["waiting_on"] is not None
        assert all(call.args[2] == 15 for call in saves.call_args_list)
        state = await reload(ctx)
        held_actor = state.get_participant(eid)
        assert held_actor is not None and held_actor.action_ledger["stolen melody"]["remaining"] == 1
        await _resolve_round(ctx)
        assert sum(call.args[2] == 20 for call in saves.call_args_list) == 1
        assert sum(call.args[2] == 15 for call in saves.call_args_list) == 1
    state = await reload(ctx)
    actor = state.get_participant(eid)
    assert actor is not None and actor.action_ledger["stolen melody"]["remaining"] == 0
    target = state.get_participant(pid)
    assert target is not None
    charm = next(c for c in target.conditions if c["type"] == "charmed")
    assert charm["source"] == eid and charm["choir_melody"] is True
