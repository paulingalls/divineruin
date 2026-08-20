"""Post-commit publish isolation for the phase loop.

Once the phase transaction commits, its HUD pushes are a mirror of an authoritative result:
a failure in one is logged, never raised (combat_events.POST_COMMIT_PUBLISH_FAILED). These
pin that each push is isolated from the others. Sharing ONE try made the first failure skip
every push behind it — and none of them re-fires, so a transient sink error left the ward
indicator and every member's Resonance track stale for the rest of the fight.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _damage_resolver, _fake_db_mod
from sample_fixtures import make_context

import combat_events
from combat_turn import _resolve_phase_impl
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
        raw = await _resolve_phase_impl(
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

    assert isinstance(raw, str), "the phase must still return its packets"
    pushed = {call.kwargs["caster_id"] for call in resonance_events_mod.publish_resonance_changed.await_args_list}
    assert pushed == {"player_1", "player_2"}, (
        "a failed sink flush must not skip the per-member Resonance pushes behind it — nothing re-pushes them"
    )
