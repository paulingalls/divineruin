"""In-combat ability resolution through declare_phase/resolve_phase (story-007, M4.2).

A player ABILITY declared into the phase loop resolves via the SHARED cast logic — deducting Focus,
generating Resonance, and composing that generation with the phase WRAP decay — in initiative order
alongside attacks (AC1/AC4). cast_spell stays the out-of-combat entry (AC3). Insufficient Focus is
covered as a unit (test_phase_loop, AC2).

Real-PG against the :55432 dev DB (dev_db_pool), with unique ids + finally-cleanup, mirroring
test_combat_tx_integrity. The cast runs for REAL (default cast_resolver=spell_casting) so Focus
deduction + Resonance generation + WRAP decay all exercise real mutations end-to-end.
"""

import json
from unittest.mock import AsyncMock, MagicMock

from combat._helpers import _damage_resolver

import combat_turn
import db_mutations
import db_queries
import spell_casting
import spells
from session_data import CombatParticipant, CombatState, SessionData


async def _seed_player(pool, player_id: str, *, focus: int, resonance: int) -> None:
    await pool.execute(
        "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
        "ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb",
        player_id,
        json.dumps(
            {
                "player_id": player_id,
                "hp": {"current": 25, "max": 25},
                "focus": {"current": focus, "max": focus},
                "resonance": {"current": resonance},
            }
        ),
    )


def _ability_vs_attack_state(combat_id: str, player_id: str, enemy_id: str, spell_id: str) -> CombatState:
    """A RESOLUTION-beat phase mixing a player ABILITY (initiative 15) and an enemy attack (12). The
    enemy (hp 20) survives the phase — the player's ability deals no HP — so combat continues and the
    WRAP decay fires (the terminal wrap that ends combat skips decay)."""
    return CombatState(
        combat_id=combat_id,
        participants=[
            CombatParticipant(id=player_id, name="Lyra", type="player", initiative=15, hp_current=25, hp_max=25, ac=14),
            CombatParticipant(
                id=enemy_id,
                name="Goblin",
                type="enemy",
                initiative=12,
                hp_current=20,
                hp_max=20,
                ac=13,
                action_pool=[{"name": "Scimitar", "damage": "1d6", "damage_type": "slashing"}],
                xp_value=50,
            ),
        ],
        initiative_order=[player_id, enemy_id],
        beat="resolution",
        pending_declarations={
            player_id: {"type": "ability", "action": spell_id},
            enemy_id: {"type": "attack", "action": "Scimitar", "target_id": player_id},
        },
    )


class TestInCombatAbilityResolution:
    async def test_mixed_attack_and_ability_resolve_with_focus_and_resonance(self, dev_db_pool) -> None:
        """AC4: a phase mixing an attack + an ability resolves both in initiative order with correct
        Focus + Resonance accounting (generation composed with the WRAP decay)."""
        pool = dev_db_pool
        player_id = "s007_ability_player"
        enemy_id = "s007_ability_enemy"
        combat_id = "combat_s007_ability"
        spell_id = "arcane_shield_spell"

        spell = spells.get_spell(spell_id)
        assert spell.focus_cost > 0, "AC needs a real Focus deduction to observe"
        generated = spell.resonance_by_source[spell.source]

        start_focus = 10
        standing_res = 5
        await _seed_player(pool, player_id, focus=start_focus, resonance=standing_res)

        session = SessionData(player_id=player_id, location_id="accord_guild_hall", room=None)
        session.resonance.current = standing_res  # the cast's in-memory base
        ctx = MagicMock()
        ctx.userdata = session
        session.combat_state = _ability_vs_attack_state(combat_id, player_id, enemy_id, spell_id)

        try:
            # Deterministic enemy attack (3 dmg); the ability runs through the REAL cast_resolver.
            raw = await combat_turn._resolve_phase_impl(ctx, resolver=_damage_resolver(3))

            assert isinstance(raw, str)  # combat continues -> JSON (not the end-of-combat handoff)
            packets = json.loads(raw)["packets"]
            # Initiative order: the player's ability (15) resolves before the enemy's attack (12).
            assert packets[0]["actor_id"] == player_id
            assert packets[0]["declaration_type"] == "ability"
            assert packets[0]["resolved"] is True
            assert packets[0]["cast"]["resonance_generated"] == generated
            assert packets[1]["actor_id"] == enemy_id
            assert packets[1]["resolved"] is True

            row = await db_queries.get_player(player_id, conn=pool)
            assert row is not None
            # Focus deducted by the spell cost (real ability_persistence write).
            assert row["focus"]["current"] == start_focus - spell.focus_cost
            # Resonance composed correctly: standing + generated (the cast) - 1 (the phase WRAP decay).
            # This single value distinguishes the correct ordering from BOTH failure modes —
            # generation-lost (standing - 1) and decay-skipped (standing + generated).
            expected = standing_res + generated - 1
            assert row["resonance"]["current"] == expected
            assert session.resonance.current == expected
        finally:
            await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)
            await db_mutations.delete_combat_state(combat_id, conn=pool)


class TestOutOfCombatCastUnaffected:
    async def test_cast_spell_out_of_combat_still_deducts_focus_and_pushes_hud(self, dev_db_pool) -> None:
        """AC3: cast_spell remains the out-of-combat entry — it still deducts Focus and pushes the
        Resonance HUD update (the in-combat path does not regress the out-of-combat one)."""
        pool = dev_db_pool
        player_id = "s007_ooc_player"
        spell_id = "arcane_shield_spell"
        spell = spells.get_spell(spell_id)
        generated = spell.resonance_by_source[spell.source]

        await _seed_player(pool, player_id, focus=10, resonance=0)

        session = SessionData(player_id=player_id, location_id="accord_guild_hall", room=None)
        ctx = MagicMock()
        ctx.userdata = session
        events = MagicMock()
        events.publish_resonance_changed = AsyncMock()

        try:
            raw = await spell_casting._cast_spell_impl(ctx, spell_id, resonance_events_mod=events)
            packet = json.loads(raw)
            assert packet["resonance_generated"] == generated

            row = await db_queries.get_player(player_id, conn=pool)
            assert row is not None
            assert row["focus"]["current"] == 10 - spell.focus_cost
            # Out of combat the cast pushes its own RESONANCE_CHANGED (no phase WRAP to own it).
            events.publish_resonance_changed.assert_awaited_once()
        finally:
            await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)
