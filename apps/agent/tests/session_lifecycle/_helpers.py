"""Shared helpers for the session-lifecycle test suite."""

from unittest.mock import MagicMock

from session_data import SessionData


def _make_context(player_id="player_1", location_id="accord_guild_hall", room=None):
    ctx = MagicMock()
    ctx.userdata = SessionData(player_id=player_id, location_id=location_id, room=room)
    return ctx
