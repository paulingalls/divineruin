"""Shared helpers for the world-query/tools test suite."""

from unittest.mock import AsyncMock, MagicMock

from session_data import SessionData


def _make_context(player_id="player_1", location_id="accord_guild_hall", room=None):
    ctx = MagicMock()
    ctx.userdata = SessionData(player_id=player_id, location_id=location_id, room=room)
    return ctx


def _make_mock_room():
    """A mock LiveKit room whose local participant captures published data."""
    room = MagicMock()
    room.local_participant = MagicMock()
    room.local_participant.publish_data = AsyncMock()
    return room


SAMPLE_PLAYER = {
    "player_id": "player_1",
    "name": "Kael",
    "class": "warrior",
    "level": 1,
    "attributes": {
        "strength": 14,
        "dexterity": 12,
        "constitution": 13,
        "intelligence": 10,
        "wisdom": 11,
        "charisma": 8,
    },
    "proficiencies": ["athletics", "stealth", "perception"],
    "saving_throw_proficiencies": ["strength", "constitution"],
    "hp": {"current": 25, "max": 25},
    "ac": 14,
}


def _skill_mocks():
    """Mock queries/mutations for a skill check: untrained, advancement-capable."""
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
    queries.get_single_skill_advancement = AsyncMock(
        return_value={"tier": "untrained", "use_counter": 0, "narrative_moment_ready": False},
    )
    mutations = MagicMock()
    mutations.update_skill_advancement = AsyncMock()
    return queries, mutations


def _save_mocks():
    """Mock queries for a saving throw (no mutation seam needed)."""
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
    return queries


SAMPLE_LOCATION = {
    "id": "accord_guild_hall",
    "name": "Guild Hall",
    "description": "Heavy oak doors open onto a hall.",
    "atmosphere": "busy, purposeful",
    "key_features": ["the main counter"],
    "hidden_elements": [{"id": "notice", "discover_skill": "perception", "dc": 10, "description": "a notice"}],
    "exits": {"south": {"destination": "accord_market_square"}},
    "tags": ["guild"],
    "conditions": {},
}
