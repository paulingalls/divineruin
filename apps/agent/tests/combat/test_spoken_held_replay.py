import pytest
from combat._helpers import _ac_sensitive_resolver, _ctx_at_resolution, _own_reaction, _resolve_deps
from combat._reaction_helpers import _drain, _enemy_blow, _guarded_ally_state, _pause_at
from voice_condition_fixtures import participant

import combat_hold
import reaction_spend
from conditions import apply_condition
from session_data import CombatState


@pytest.mark.asyncio
@pytest.mark.parametrize("restriction_at_roll", [False, True])
@pytest.mark.parametrize("reload", [False, True])
@pytest.mark.parametrize("halve", [False, True])
async def test_delivery_changes_after_roll_cannot_change_published_attack(restriction_at_roll, reload, halve):
    state = _guarded_ally_state()
    _own_reaction(state, "marshal_interceding_order")
    ally = participant(state, "player_2")
    ally.has_reaction_ability = True
    ally.reaction_ids = ["rogue_uncanny_dodge"]
    ctx = _ctx_at_resolution(state=state)
    from unittest.mock import MagicMock

    from sample_fixtures import published_events

    import event_types as E

    ctx.userdata.event_bus = MagicMock()
    resolver = _ac_sensitive_resolver(attack_total=17, damage=4)
    deps = {**_resolve_deps(), "resolver": resolver}
    packets = []
    await _pause_at(ctx, deps, actor_id="goblin_scout_1", stage="pre_roll", packets=packets)
    state = ctx.userdata.combat_state
    combat_hold.record_spend(
        state, "player_1", reaction_spend.spend("marshal_interceding_order", state.open_window, held_seq=0)
    )
    if restriction_at_roll:
        participant(state, "player_2").conditions = apply_condition([], "deafened", source="test")
    if reload:
        ctx.userdata.combat_state = CombatState.from_dict(state.to_dict())
    await _pause_at(ctx, deps, actor_id="goblin_scout_1", stage="post_roll", packets=packets)
    state = ctx.userdata.combat_state
    assert state.open_window is not None
    head = state.held_actions[0]
    expected = 0 if restriction_at_roll else 2
    assert head.get("reaction_ac_bonus") == expected
    before = head["roll"].copy()
    if halve:
        combat_hold.record_spend(
            state, "player_2", reaction_spend.spend("rogue_uncanny_dodge", state.open_window, held_seq=0)
        )
    participant(state, "player_2").conditions = (
        [] if restriction_at_roll else apply_condition([], "deafened", source="test")
    )
    if reload:
        ctx.userdata.combat_state = CombatState.from_dict(state.to_dict())
    try:
        await _drain(ctx, deps, packets)
    except ValueError as exc:
        pytest.fail(f"Published held attack cannot land: {exc}")
    blow = _enemy_blow(packets)
    damage = 2 if halve else 4
    assert (blow["hit"], blow["damage"], blow["target_ac"]) == (True, damage, 14 + expected)
    assert before["effective_ac"] == blow["target_ac"]
    assert participant(ctx.userdata.combat_state, "player_2").hp_current == 20 - damage
    dice = [
        event.payload
        for event in published_events(ctx)
        if event.event_type == E.DICE_ROLL and event.payload.get("roll_type") == "attack"
    ]
    assert len(dice) == 1 and dice[0]["damage"] == 4
    assert head.get("reaction_ac_bonus") == expected
    assert resolver.resolve_attack.call_count == 1


@pytest.mark.parametrize("contribution", [None, False, True, "2", -1, 1, 3])
def test_rolled_head_rejects_missing_or_corrupt_contribution_at_real_load(contribution):
    from combat._helpers import _damage_resolver

    from combat_attack_roll import serialize_roll
    from combat_support import roll_attack

    state = _guarded_ally_state()
    attacker = participant(state, "goblin_scout_1")
    target = participant(state, "player_2")
    result, ac = roll_attack(
        attacker, attacker.action_pool[0], target, resolver=_damage_resolver(4), combat_state=state
    )
    state.held_actions = [
        {
            "seq": 0,
            "actor_id": attacker.id,
            "initiative": 12,
            "declaration": {"type": "attack", "action": "Scimitar", "target_id": target.id},
            "roll": serialize_roll(result, ac),
            "opened": [],
        }
    ]
    if contribution is not None:
        state.held_actions[0]["reaction_ac_bonus"] = contribution
    with pytest.raises(ValueError, match="reaction AC"):
        CombatState.from_dict(state.to_dict())
    with pytest.raises(ValueError, match="reaction AC"):
        combat_hold._replay_resolver(state.held_actions[0])


@pytest.mark.asyncio
async def test_failed_roll_commit_preserves_head_spend_and_publication(dev_db_pool, monkeypatch):
    import json
    import uuid
    from unittest.mock import AsyncMock

    from combat._helpers import _call

    import combat_events
    import db
    import db_mutations
    from session_data import SessionData

    suffix = uuid.uuid4().hex
    host, ally, enemy = ("held-host-" + suffix, "held-ally-" + suffix, "held-enemy-" + suffix)
    state = _guarded_ally_state()
    _own_reaction(state, "marshal_interceding_order")
    participant(state, "player_2").has_reaction_ability = True
    participant(state, "player_2").reaction_ids = ["rogue_uncanny_dodge"]
    raw = (
        json.dumps(state.to_dict()).replace("player_1", host).replace("player_2", ally).replace("goblin_scout_1", enemy)
    )
    state = CombatState.from_dict(json.loads(raw))
    state.combat_id = "held-spoken-" + suffix
    pool = dev_db_pool
    for pid, hp in ((host, 25), (ally, 20)):
        await pool.execute(
            "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb)",
            pid,
            json.dumps({"player_id": pid, "hp": {"current": hp, "max": hp}}),
        )
    ctx = _ctx_at_resolution(state=state)
    ctx.userdata = SessionData(player_id=host, location_id="accord_guild_hall")
    ctx.userdata.combat_state = state
    deps = {
        **_resolve_deps(),
        "mutations": db_mutations,
        "db_mod": db,
        "resolver": _ac_sensitive_resolver(attack_total=17, damage=4),
    }
    packets = []
    try:
        await _pause_at(ctx, deps, actor_id=enemy, stage="pre_roll", packets=packets)
        state = ctx.userdata.combat_state
        assert state is not None and state.open_window is not None
        combat_hold.record_spend(
            state, host, reaction_spend.spend("marshal_interceding_order", state.open_window, held_seq=0)
        )
        await db_mutations.save_combat_state(state.combat_id, state.to_dict())
        before = state.to_dict()
        save = db_mutations.save_combat_state

        async def fail_after_save(*args, **kwargs):
            await save(*args, **kwargs)
            raise RuntimeError("fault after frozen roll save")

        flush = AsyncMock()
        with monkeypatch.context() as fault:
            fault.setattr(db_mutations, "save_combat_state", fail_after_save)
            fault.setattr(combat_events.EventSink, "flush", flush)
            with pytest.raises(RuntimeError, match="frozen roll"):
                await _call(ctx, deps)
        flush.assert_not_awaited()
        assert ctx.userdata.combat_state is state and state.to_dict() == before
        persisted = await db_mutations.load_combat_state(state.combat_id)
        assert persisted is not None and persisted.to_dict() == before
        await _call(ctx, deps)
        persisted = await db_mutations.load_combat_state(state.combat_id)
        assert persisted is not None
        assert persisted.held_actions[0]["reaction_ac_bonus"] == 2
        assert persisted.held_actions[0]["roll_published"] is True
        assert reaction_spend.is_spent(persisted.reactions_available[host])
    finally:
        await db_mutations.delete_combat_state(state.combat_id)
        await pool.execute("DELETE FROM players WHERE player_id = ANY($1::text[])", [host, ally])
