"""COMBAT_UI_UPDATE timing at pause commits, non-terminal wraps, and terminal wraps."""

import json
from unittest.mock import MagicMock

from _combat_end_fixtures import combat_end_queries
from combat._helpers import (
    _call,
    _ctx_at_resolution,
    _damage_resolver,
    _resolution_state,
    _resolve_deps,
    _resolve_round,
)
from combat._reaction_helpers import _guarded_ally_state, _pause_at

import db_mutations
import event_types as E
import reaction_windows
from session_data import SessionData


async def _seed_player(pool, player_id: str) -> None:
    await pool.execute(
        "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
        "ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb",
        player_id,
        json.dumps({"player_id": player_id, "attributes": {"wisdom": 14}, "level": 5}),
    )


def _saves_always_resolver():
    """A check_resolution_save mock whose every roll succeeds — so any save-to-clear
    condition at the Beat-4 tick gets removed. Used to drive the post-tick assertion."""
    mock = MagicMock()
    result = MagicMock()
    result.success = True
    mock.resolve_saving_throw = MagicMock(return_value=result)
    return mock


async def test_resolve_phase_emits_combat_ui_update_at_wrap_with_post_tick_conditions(dev_db_pool):
    """After a Beat-4 wrap save-to-clear removes a Frightened, the emitted
    COMBAT_UI_UPDATE packet shows the participant WITHOUT that condition.
    Proves the emit reads the post-tick state, not the pre-tick snapshot."""
    pool = dev_db_pool
    player_id = "m12_s001_post_tick_player"
    enemy_id = "m12_s001_post_tick_enemy"
    combat_id = "combat_m12_s001_post_tick"
    await _seed_player(pool, player_id)

    frightened = [{"type": "frightened", "duration": 3, "source": "shaman_aura", "stacks": 1}]
    session = SessionData(player_id=player_id, location_id="accord_guild_hall", room=None)
    ctx = MagicMock()
    ctx.userdata = session
    session.combat_state = _resolution_state(
        combat_id=combat_id,
        player_id=player_id,
        enemy_id=enemy_id,
        player_conditions=frightened,
        player_attributes={"wisdom": 14},
        player_level=5,
    )

    try:
        await _resolve_round(
            ctx,
            resolver=_damage_resolver(1),  # token damage; doesn't drop the enemy
            save_resolver=_saves_always_resolver(),
        )
        events = list(session.event_bus.drain())
        ui_updates = [e for e in events if e.event_type == E.COMBAT_UI_UPDATE]
        assert len(ui_updates) == 2, f"expected ally-commit + wrap updates, got {[e.event_type for e in events]}"

        packet = ui_updates[-1].payload
        by_id = {c["id"]: c for c in packet["combatants"]}
        player_combatant = by_id[player_id]
        assert all(c["type"] != "frightened" for c in player_combatant["conditions"]), (
            f"post-tick conditions still include frightened: {player_combatant['conditions']}"
        )
    finally:
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)
        await db_mutations.delete_combat_state(combat_id, conn=pool)


async def test_resolve_phase_skips_combat_ui_update_on_terminal_wrap(dev_db_pool):
    """When the wrap ends combat (all enemies fallen), no COMBAT_UI_UPDATE is
    emitted — COMBAT_ENDED + the mobile hudStore.clearCombatState path takes
    over the HUD teardown, and a same-flush UI_UPDATE would flash state on then off."""
    pool = dev_db_pool
    player_id = "m12_s001_terminal_player"
    enemy_id = "m12_s001_terminal_enemy"
    combat_id = "combat_m12_s001_terminal"
    await _seed_player(pool, player_id)

    session = SessionData(player_id=player_id, location_id="accord_guild_hall", room=None)
    ctx = MagicMock()
    ctx.userdata = session
    # Enemy starts at 1 HP; the player's 5-damage swing drops it -> wrap reports victory.
    session.combat_state = _resolution_state(combat_id=combat_id, player_id=player_id, enemy_id=enemy_id, enemy_hp=1)

    # end_combat reads each player's row (XP grant) + inventory (durability accrual); no items
    # equipped in this fixture, so a zero-row inventory keeps the durability path silent.
    queries = combat_end_queries()

    try:
        deps = {"resolver": _damage_resolver(5), "queries": queries}
        await _call(ctx, deps)
        session.event_bus.drain()
        await _resolve_round(ctx, **deps)
        events = [e.event_type for e in session.event_bus.drain()]
        assert E.COMBAT_ENDED in events, f"expected COMBAT_ENDED in {events}"
        assert E.COMBAT_UI_UPDATE not in events, f"COMBAT_UI_UPDATE leaked on terminal wrap: {events}"
    finally:
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)
        # end_combat already deleted the row; this is the safety net for a partial-run.
        await db_mutations.delete_combat_state(combat_id, conn=pool)


async def test_ally_commit_emits_ui_update_with_the_ally_bands_damage():
    ctx = _ctx_at_resolution(enemy_hp=20)

    paused = await _call(ctx, _resolve_deps(damage=3))

    assert paused["next"]["waiting_on"] is None
    assert ctx.userdata.combat_state.held_actions
    updates = [event for event in ctx.userdata.event_bus.drain() if event.event_type == E.COMBAT_UI_UPDATE]
    assert len(updates) == 1
    combatants = {combatant["id"]: combatant for combatant in updates[0].payload["combatants"]}
    assert combatants["goblin_scout_1"]["hpCurrent"] == 17


async def test_pre_roll_pause_emits_ui_update_with_the_ally_bands_damage():
    ctx = _ctx_at_resolution(enemy_hp=20)
    deps = _resolve_deps(damage=3)

    await _call(ctx, deps)
    ctx.userdata.event_bus.drain()
    paused = await _call(ctx, deps)

    assert paused["next"]["waiting_on"]["stage"] == reaction_windows.PRE_ROLL
    updates = [event for event in ctx.userdata.event_bus.drain() if event.event_type == E.COMBAT_UI_UPDATE]
    assert len(updates) == 1
    combatants = {combatant["id"]: combatant for combatant in updates[0].payload["combatants"]}
    assert combatants["goblin_scout_1"]["hpCurrent"] == 17


async def test_pause_ui_update_reads_damage_applied_in_the_pausing_call():
    state = _guarded_ally_state(enemy_ids=("goblin_scout_1", "goblin_scout_2"))
    ctx = _ctx_at_resolution(state=state)
    deps = _resolve_deps(damage=3)
    packets: list[dict] = []
    await _pause_at(
        ctx,
        deps,
        actor_id="goblin_scout_1",
        stage=reaction_windows.POST_ROLL,
        packets=packets,
    )
    ctx.userdata.event_bus.drain()

    paused = await _call(ctx, deps)

    assert paused["next"]["waiting_on"]["actor_id"] == "goblin_scout_2"
    assert paused["next"]["waiting_on"]["stage"] == reaction_windows.PRE_ROLL
    updates = [event for event in ctx.userdata.event_bus.drain() if event.event_type == E.COMBAT_UI_UPDATE]
    assert len(updates) == 1
    combatants = {combatant["id"]: combatant for combatant in updates[0].payload["combatants"]}
    assert combatants["player_2"]["hpCurrent"] == 17
