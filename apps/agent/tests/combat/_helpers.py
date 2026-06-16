"""Shared helpers for the combat-tools test suite."""

from unittest.mock import MagicMock

from sample_fixtures import make_db_mod

from check_resolution import AttackResult
from session_data import CombatParticipant, CombatState


def _fake_db_mod():
    """A db-module stand-in for resolve_phase unit tests: ``.transaction()`` is a no-op async
    context manager yielding a mock conn, so the per-phase transaction wrapper (story-010) runs
    without a real DB (the mocked mutations accept + ignore the conn kwarg). Delegates to the
    canonical sample_fixtures.make_db_mod so the transaction plumbing lives in one place."""
    db_mod, _conn = make_db_mod()
    return db_mod


def _make_combat_state(player_hp=25, player_fallen=False, enemy_hp=7, enemy_fallen=False):
    """Create a CombatState for testing."""
    return CombatState(
        combat_id="combat_test123",
        participants=[
            CombatParticipant(
                id="player_1",
                name="Kael",
                type="player",
                initiative=15,
                hp_current=player_hp,
                hp_max=25,
                ac=14,
                is_fallen=player_fallen,
            ),
            CombatParticipant(
                id="goblin_scout_1",
                name="Goblin Scout",
                type="enemy",
                initiative=12,
                hp_current=enemy_hp,
                hp_max=7,
                ac=13,
                action_pool=[
                    {
                        "name": "Scimitar",
                        "damage": "1d6",
                        "damage_type": "slashing",
                        "properties": ["light"],
                    },
                ],
                xp_value=50,
                is_fallen=enemy_fallen,
            ),
        ],
        initiative_order=["player_1", "goblin_scout_1"],
        round_number=1,
        current_turn_index=0,
        location_id="accord_guild_hall",
    )


def _resolution_state(player_hp=25, enemy_hp=7):
    """A CombatState parked at the RESOLUTION beat with player+enemy declarations
    pending. The player carries a synthesized weapon action_pool (story-003 step 6
    builds this at init; constructed inline here)."""
    return CombatState(
        combat_id="combat_test123",
        participants=[
            CombatParticipant(
                id="player_1",
                name="Kael",
                type="player",
                initiative=15,
                hp_current=player_hp,
                hp_max=25,
                ac=14,
                action_pool=[{"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}],
            ),
            CombatParticipant(
                id="goblin_scout_1",
                name="Goblin Scout",
                type="enemy",
                initiative=12,
                hp_current=enemy_hp,
                hp_max=7,
                ac=13,
                action_pool=[{"name": "Scimitar", "damage": "1d6", "damage_type": "slashing", "properties": ["light"]}],
                xp_value=50,
            ),
        ],
        initiative_order=["player_1", "goblin_scout_1"],
        round_number=1,
        current_turn_index=0,
        location_id="accord_guild_hall",
        beat="resolution",
        pending_declarations={
            "player_1": {"type": "attack", "action": "Longsword", "target_id": "goblin_scout_1"},
            "goblin_scout_1": {"type": "attack", "action": "Scimitar", "target_id": "player_1"},
        },
    )


def _damage_resolver(damage):
    """A resolve_attack mock that always hits for a fixed damage, computing the target's
    remaining HP from the call args so multiple packets resolve coherently."""

    def _resolve(attacker_data, action, target_ac, target_hp):
        remaining = max(0, target_hp - damage)
        return AttackResult(
            hit=True,
            roll=15,
            attack_modifier=3,
            attack_total=18,
            target_ac=target_ac,
            damage=damage,
            damage_type="slashing",
            critical_success=False,
            critical_failure=False,
            target_hp_remaining=remaining,
            target_killed=remaining == 0,
            narrative_hint="A clean strike.",
        )

    r = MagicMock()
    r.resolve_attack = MagicMock(side_effect=_resolve)
    return r
