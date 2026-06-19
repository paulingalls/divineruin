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
