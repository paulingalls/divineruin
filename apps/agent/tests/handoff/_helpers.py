"""Shared helpers for agent-handoff integration tests."""

from unittest.mock import MagicMock

from session_data import SessionData


def make_context(location_id="greyvale_south_road"):
    ctx = MagicMock()
    ctx.userdata = SessionData(player_id="player_1", location_id=location_id)
    ctx.session = MagicMock()
    ctx.session.current_agent = None
    return ctx
