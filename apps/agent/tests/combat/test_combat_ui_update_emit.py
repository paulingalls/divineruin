"""resolve_phase emit-timing tests for COMBAT_UI_UPDATE (M12, story-001).

The pure packet builder is covered by tests/test_combat_ui_update.py; this
file pins the emit placement inside _resolve_phase_impl:

- At Beat-4 wrap POST-tick (save-cleared conditions are absent from the
  emitted packet).
- ONLY when the wrap does NOT end combat (terminal wrap relies on
  COMBAT_ENDED + the mobile clearCombatState path).
- Via the buffered EventSink (so a rolled-back tx publishes nothing).

Uses the shared dev DB (:55432) for the player row that _prevalidate_ability_focus
would read; non-ability declarations don't actually need it, but we follow the
project convention for resolve_phase tests.
"""

import json
from unittest.mock import AsyncMock, MagicMock

from combat._helpers import _damage_resolver

import combat_turn
import db_mutations
import event_types as E
from session_data import CombatParticipant, CombatState, SessionData


async def _seed_player(pool, player_id: str) -> None:
    await pool.execute(
        "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
        "ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb",
        player_id,
        json.dumps({"player_id": player_id, "attributes": {"wisdom": 14}, "level": 5}),
    )


def _resolution_state(combat_id, player_id, enemy_id, *, enemy_hp=7, player_conditions=None):
    return CombatState(
        combat_id=combat_id,
        participants=[
            CombatParticipant(
                id=player_id,
                name="Kael",
                type="player",
                initiative=15,
                hp_current=25,
                hp_max=25,
                ac=14,
                attributes={"wisdom": 14},
                level=5,
                action_pool=[{"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}],
                conditions=player_conditions or [],
            ),
            CombatParticipant(
                id=enemy_id,
                name="Goblin",
                type="enemy",
                initiative=12,
                hp_current=enemy_hp,
                hp_max=7,
                ac=13,
                action_pool=[{"name": "Scimitar", "damage": "1d6", "damage_type": "slashing"}],
                xp_value=50,
            ),
        ],
        initiative_order=[player_id, enemy_id],
        beat="resolution",
        pending_declarations={
            player_id: {"type": "attack", "action": "Longsword", "target_id": enemy_id},
            enemy_id: {"type": "attack", "action": "Scimitar", "target_id": player_id},
        },
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
    session.combat_state = _resolution_state(combat_id, player_id, enemy_id, enemy_hp=7, player_conditions=frightened)

    try:
        await combat_turn._resolve_phase_impl(
            ctx,
            resolver=_damage_resolver(1),  # token damage; doesn't drop the enemy
            save_resolver=_saves_always_resolver(),
        )
        events = list(session.event_bus.drain())
        ui_updates = [e for e in events if e.event_type == E.COMBAT_UI_UPDATE]
        assert len(ui_updates) == 1, f"expected one COMBAT_UI_UPDATE, got {[e.event_type for e in events]}"

        packet = ui_updates[0].payload
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
    session.combat_state = _resolution_state(combat_id, player_id, enemy_id, enemy_hp=1)

    try:
        await combat_turn._resolve_phase_impl(
            ctx,
            resolver=_damage_resolver(5),
            queries=_no_inventory_queries(),
        )
        events = [e.event_type for e in session.event_bus.drain()]
        assert E.COMBAT_ENDED in events, f"expected COMBAT_ENDED in {events}"
        assert E.COMBAT_UI_UPDATE not in events, f"COMBAT_UI_UPDATE leaked on terminal wrap: {events}"
    finally:
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)
        # end_combat already deleted the row; this is the safety net for a partial-run.
        await db_mutations.delete_combat_state(combat_id, conn=pool)


def _no_inventory_queries() -> MagicMock:
    """end_combat reads player inventory for durability accrual; the terminal-wrap test
    has no items equipped, so a zero-row stub keeps the path silent."""
    queries = MagicMock()
    queries.get_player_inventory = AsyncMock(return_value=[])
    return queries
