"""Shared helpers for the world-query/tools test suite."""

from unittest.mock import MagicMock

from session_data import SessionData


def _make_context(player_id="player_1", location_id="accord_guild_hall"):
    ctx = MagicMock()
    ctx.userdata = SessionData(player_id=player_id, location_id=location_id)
    return ctx


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
