"""Post-commit isolation, ordering, and one-shot publication for the phase loop."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import (
    _activate,
    _call,
    _ctx_at_resolution,
    _damage_resolver,
    _fake_db_mod,
    _resolve_deps,
    _resolve_round,
)
from sample_fixtures import make_context

import combat_events
import combat_hold
import combat_support
import event_types as E
import reaction_windows
from session_data import CombatParticipant, CombatState


def _two_pc_resolution_state() -> CombatState:
    """Two PCs and one high-HP enemy at the RESOLUTION beat. Nothing dies this phase, so the WRAP
    runs its Resonance decay and the loop stays in combat."""
    weapon = [{"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}]
    return CombatState(
        combat_id="combat_publish_isolation",
        participants=[
            CombatParticipant(
                id="player_1",
                name="Kael",
                type="player",
                initiative=20,
                hp_current=25,
                hp_max=25,
                ac=14,
                action_pool=weapon,
            ),
            CombatParticipant(
                id="player_2",
                name="Sera",
                type="player",
                initiative=15,
                hp_current=25,
                hp_max=25,
                ac=14,
                action_pool=weapon,
            ),
            CombatParticipant(
                id="goblin_1",
                name="Goblin",
                type="enemy",
                initiative=1,
                hp_current=100,
                hp_max=100,
                ac=13,
                action_pool=[{"name": "Scimitar", "damage": "1d6", "damage_type": "slashing", "properties": ["light"]}],
                xp_value=50,
            ),
        ],
        initiative_order=["player_1", "player_2", "goblin_1"],
        round_number=1,
        current_turn_index=0,
        location_id="accord_guild_hall",
        beat="resolution",
        pending_declarations={
            "player_1": {"type": "attack", "action": "Longsword", "target_id": "goblin_1"},
            "player_2": {"type": "attack", "action": "Longsword", "target_id": "goblin_1"},
            "goblin_1": {"type": "attack", "action": "Scimitar", "target_id": "player_1"},
        },
    )


@pytest.mark.asyncio
async def test_a_failing_sink_flush_does_not_swallow_the_resonance_pushes():
    ctx = make_context(party_member_ids=["player_2"])
    ctx.userdata.combat_state = _two_pc_resolution_state()
    # Both members carry Resonance, so the WRAP's decay puts them in pending_by_member and each
    # owes exactly one authoritative RESONANCE_CHANGED push.
    for member in ctx.userdata.party.members:
        member.resonance.current = 5

    mutations = MagicMock()
    mutations.save_combat_state = AsyncMock()
    mutations.update_player_hp = AsyncMock()
    queries = MagicMock()
    queries.get_player_inventory = AsyncMock(return_value=[])
    queries.get_player = AsyncMock(return_value={"player_id": "player_1", "focus": {"current": 10, "max": 10}})
    break_mod = MagicMock()
    break_mod.break_concentration_on_damage = AsyncMock(return_value=None)
    resonance_mutations = MagicMock()
    resonance_mutations.update_player_resonance = AsyncMock()
    resonance_events_mod = MagicMock()
    resonance_events_mod.publish_resonance_changed = AsyncMock()

    # EventSink.flush replays through combat_events.publish_game_event; make every replay blow up.
    original_publish = combat_events.publish_game_event
    combat_events.publish_game_event = AsyncMock(side_effect=RuntimeError("publish boom"))
    try:
        raw = await _resolve_round(
            ctx,
            mutations=mutations,
            queries=queries,
            resolver=_damage_resolver(0),
            concentration_break_mod=break_mod,
            resonance_mutations=resonance_mutations,
            resonance_events_mod=resonance_events_mod,
            db_mod=_fake_db_mod(),
        )
    finally:
        combat_events.publish_game_event = original_publish

    assert not isinstance(raw, tuple), "the phase must still return its packets"
    pushed = {call.kwargs["caster_id"] for call in resonance_events_mod.publish_resonance_changed.await_args_list}
    assert pushed == {"player_1", "player_2"}, (
        "a failed sink flush must not skip the per-member Resonance pushes behind it — nothing re-pushes them"
    )


@pytest.mark.asyncio
async def test_post_roll_pause_publishes_the_attack_once_before_the_hud():
    ctx = _ctx_at_resolution(reaction_ids=("rogue_uncanny_dodge",))
    deps = _resolve_deps(damage=6)
    await _call(ctx, deps)
    ctx.userdata.event_bus.drain()

    original = combat_hold.build_attack_dice_roll_payload
    builder = MagicMock(wraps=original)
    combat_hold.build_attack_dice_roll_payload = builder
    try:
        paused = await _call(ctx, deps)
    finally:
        combat_hold.build_attack_dice_roll_payload = original

    assert paused["next"]["waiting_on"]["stage"] == reaction_windows.POST_ROLL
    head = ctx.userdata.combat_state.held_actions[0]
    result, _effective_ac = combat_support.deserialize_roll(head["roll"])
    builder.assert_called_once_with(ctx.userdata.combat_state.get_participant(head["actor_id"]), result)
    events = list(ctx.userdata.event_bus.drain())
    assert [event.event_type for event in events] == [E.DICE_ROLL, E.COMBAT_UI_UPDATE]
    roll = events[0].payload
    assert (roll["modifier"], roll["total"], roll["success"], roll["narrative"]) == (
        result.attack_modifier,
        result.attack_total,
        result.hit,
        result.narrative_hint,
    )

    await _activate(ctx, "rogue_uncanny_dodge", player_class="rogue")
    final = await _call(ctx, deps)
    later_events = list(ctx.userdata.event_bus.drain())
    assert not [event for event in later_events if event.event_type == E.DICE_ROLL]
    enemy_packets = [packet for packet in final["packets"] if packet.get("actor_id") == "goblin_scout_1"]
    assert enemy_packets[0]["damage"] == 3
    assert ctx.userdata.combat_state.get_participant("player_1").hp_current == 22


@pytest.mark.asyncio
async def test_rolled_back_post_roll_pause_publishes_neither_event():
    ctx = _ctx_at_resolution(reaction_ids=("skirmisher_sidestep", "rogue_uncanny_dodge"))
    deps = _resolve_deps(damage=6)
    await _call(ctx, deps)
    ctx.userdata.event_bus.drain()
    await _call(ctx, deps)
    ctx.userdata.event_bus.drain()
    deps["mutations"].save_combat_state.side_effect = RuntimeError("save failed")

    with pytest.raises(RuntimeError, match="save failed"):
        await _call(ctx, deps)

    assert list(ctx.userdata.event_bus.drain()) == []
    head = ctx.userdata.combat_state.held_actions[0]
    assert head["roll"] is None
    assert ctx.userdata.combat_state.open_window["stage"] == reaction_windows.PRE_ROLL
