"""M12 capstone — E2E COMBAT_UI_UPDATE round-trip (sprint-029).

Exercises the full producer chain end to end:
    apply_condition (pre-resolve) -> declare_phase -> resolve_phase
        -> _resolve_tick_saves (Beat-4 wrap, condition cleared)
        -> build_combat_ui_update (post-tick state)
        -> emit_or_publish (buffered sink)
        -> sink.flush (post-commit)
        -> session.event_bus

Locks the contract loop: the packet's field set + condition projection must
match what story-002 pinned on the mobile parser (parseCombatant +
parseCondition in apps/mobile/src/audio/game-event-handler.ts). A future
producer rename or shape drift surfaces here as a red capstone.

Lane: testcontainer Postgres + real combat tx (mirrors the M4.x capstones).
"""

from unittest.mock import patch

from acceptance._capstone_helpers import (
    _build_state,
    _d20,
    _enemy,
    _start_combat,
)
from sample_fixtures import make_context, make_mock_room

import combat_turn
import conditions
import db
import db_mutations
import event_types as E

# Mirror the mobile parseCombatant + parseCondition contract (story-002).
_EXPECTED_PACKET_KEYS = {"phase", "round", "combatants"}
_EXPECTED_COMBATANT_KEYS = {
    "id",
    "name",
    "isAlly",
    "hpCurrent",
    "hpMax",
    "conditions",
    "isActive",
}
_EXPECTED_CONDITION_KEYS = {"type", "stacks", "source"}


async def test_m12_combat_ui_update_round_trip_post_tick_conditions(reset_db_pool: str) -> None:
    """A real combat phase with a player carrying Blessed (persists) + Frightened
    (cleared by a forced-success WIS save at the wrap) emits one COMBAT_UI_UPDATE.

    The packet's combatant shape mirrors the mobile parseCombatant contract
    verbatim, its conditions carry only {type, stacks, source}, and the player's
    post-tick conditions show Blessed still present and Frightened gone — proving
    the producer reads state AFTER the Beat-4 tick.
    """
    pool = await db.get_pool()
    player_id = "cap_m12_round_trip"
    state = _build_state("combat_cap_m12_round_trip", player_id, [_enemy("goblin_a", hp=100)])
    player = state.get_participant(player_id)
    assert player is not None

    # Blessed: duration=None so the wrap tick never decrements it (the +1d4 is
    # consumed_on_use, not duration-bound) — survives this phase intact.
    player.conditions = conditions.apply_condition(player.conditions, "blessed", source="divine_bless")
    # Frightened: save-to-clear at the wrap; forced d20=20 succeeds (>= DC 10).
    player.conditions = conditions.apply_condition(player.conditions, "frightened", source="wraith")

    ctx = make_context(player_id, room=make_mock_room())
    try:
        await _start_combat(pool, player_id, state, ctx)
        # Player Defends — no d20 attack roll, so Blessed's consumed-on-use bonus die
        # stays alive past resolve (we want it visible in the post-tick packet). Enemy
        # still swings so the phase has real work to resolve.
        decls = {
            player_id: {"type": "defend"},
            "goblin_a": {"type": "attack", "action": "Scimitar", "target_id": player_id},
        }
        await combat_turn._declare_phase_impl(ctx, decls)
        with patch("check_resolution.dice_roll", return_value=_d20(20)):
            await combat_turn._resolve_phase_impl(ctx)

        events = list(ctx.userdata.event_bus.drain())
        ui_updates = [e for e in events if e.event_type == E.COMBAT_UI_UPDATE]
        assert len(ui_updates) == 1, f"expected exactly one COMBAT_UI_UPDATE, got {[e.event_type for e in events]}"

        packet = ui_updates[0].payload

        # Packet top-level shape — exactly what the mobile handler reads.
        assert set(packet.keys()) == _EXPECTED_PACKET_KEYS

        # Every combatant matches the parseCombatant contract verbatim.
        for combatant in packet["combatants"]:
            assert set(combatant.keys()) == _EXPECTED_COMBATANT_KEYS, (
                f"combatant {combatant.get('id')} shape drift: {set(combatant.keys())}"
            )

        by_id = {c["id"]: c for c in packet["combatants"]}
        assert set(by_id) == {player_id, "goblin_a"}

        # Player end-state: Blessed persists (its duration is None → wrap tick is a no-op),
        # Frightened gone (forced save). Conditions carry only {type, stacks, source}.
        player_combatant = by_id[player_id]
        assert player_combatant["isAlly"] is True
        condition_types = [c["type"] for c in player_combatant["conditions"]]
        assert "blessed" in condition_types, f"blessed missing from post-tick packet: {condition_types}"
        assert "frightened" not in condition_types, (
            f"frightened survived the forced-success WIS save: {condition_types}"
        )
        for cond in player_combatant["conditions"]:
            assert set(cond.keys()) == _EXPECTED_CONDITION_KEYS, (
                f"condition shape drift (duration/stage leaked to wire?): {cond}"
            )
        # Blessed projection is the canonical {type, stacks, source} (stacks default 1).
        blessed = next(c for c in player_combatant["conditions"] if c["type"] == "blessed")
        assert blessed == {"type": "blessed", "stacks": 1, "source": "divine_bless"}

        # Enemy: isAlly false, no leaked conditions.
        enemy_combatant = by_id["goblin_a"]
        assert enemy_combatant["isAlly"] is False

        # Exactly one combatant is isActive (the next-up actor at
        # initiative_order[current_turn_index]); after the wrap that index reset to 0.
        active_ids = [c["id"] for c in packet["combatants"] if c["isActive"]]
        assert len(active_ids) == 1, f"expected one isActive combatant, got {active_ids}"
    finally:
        await db_mutations.delete_combat_state(state.combat_id, conn=pool)
