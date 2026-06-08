"""Shared helpers for the combat-tools test suite."""

from unittest.mock import AsyncMock, MagicMock

from session_data import CombatParticipant, CombatState, SessionData


def _make_context(player_id="player_1", location_id="accord_guild_hall", room=None):
    ctx = MagicMock()
    ctx.userdata = SessionData(player_id=player_id, location_id=location_id, room=room)
    return ctx


def _make_mock_room():
    room = MagicMock()
    room.local_participant = MagicMock()
    room.local_participant.publish_data = AsyncMock()
    return room


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
            ),
        ],
        initiative_order=["player_1", "goblin_scout_1"],
        round_number=1,
        current_turn_index=0,
        location_id="accord_guild_hall",
    )
