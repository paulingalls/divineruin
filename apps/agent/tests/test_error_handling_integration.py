"""Translate DB failures to ToolError so the model can narrate them."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents.llm import ToolError

from session_data import SessionData
from session_tools import update_npc_disposition

_NPC = {"id": "torin", "name": "Torin", "default_disposition": "neutral"}


def _context():
    context = MagicMock()
    context.userdata = SessionData(
        room=MagicMock(),
        event_bus=MagicMock(),
        player_id="test_player",
        location_id="test_location",
    )
    return context


def _npc_lookups():
    """Patch the two reads that precede the transaction (content fetch + presence guard),
    so the flow actually reaches the db.transaction under test."""
    return (
        patch("db_content_queries.get_npc", new_callable=AsyncMock, return_value=_NPC),
        patch("db_queries.get_npcs_at_location", new_callable=AsyncMock, return_value=[{"id": "torin"}]),
    )


@pytest.mark.asyncio
async def test_db_tool_connection_error_returns_tool_error():
    context = _context()
    get_npc, present = _npc_lookups()

    with get_npc, present, patch("db.transaction") as mock_txn:
        mock_txn.side_effect = ConnectionError("Database unreachable")

        with pytest.raises(ToolError, match="trouble accessing"):
            await update_npc_disposition(context, npc_id="torin", delta=1, reason="test")


@pytest.mark.asyncio
async def test_db_tool_timeout_returns_tool_error():
    context = _context()
    get_npc, present = _npc_lookups()

    with get_npc, present, patch("db.transaction") as mock_txn:
        mock_txn.side_effect = TimeoutError("Query took too long")

        with pytest.raises(ToolError, match="longer than expected"):
            await update_npc_disposition(context, npc_id="torin", delta=1, reason="test")


@pytest.mark.asyncio
async def test_db_tool_rollback_prevents_partial_state():
    context = _context()
    session = context.userdata
    initial_events = len(session.recent_events)
    get_npc, present = _npc_lookups()

    with (
        get_npc,
        present,
        patch("db.transaction") as mock_txn,
        patch("db_queries.get_npc_disposition", new_callable=AsyncMock, return_value="neutral"),
        patch(
            "db_mutations.set_npc_disposition",
            new_callable=AsyncMock,
            side_effect=ConnectionError("DB write failed"),
        ),
    ):
        mock_txn.return_value.__aenter__.return_value = AsyncMock()

        with pytest.raises(ToolError):
            await update_npc_disposition(context, npc_id="torin", delta=1, reason="test")

        assert len(session.recent_events) == initial_events


@pytest.mark.asyncio
async def test_db_tool_succeeds_normally_after_an_error():
    context = _context()
    get_npc, present = _npc_lookups()

    with get_npc, present, patch("db.transaction") as mock_txn:
        mock_txn.side_effect = ConnectionError("Temporary failure")
        with pytest.raises(ToolError):
            await update_npc_disposition(context, npc_id="torin", delta=1, reason="test")

    get_npc, present = _npc_lookups()
    with (
        get_npc,
        present,
        patch("db.transaction") as mock_txn,
        patch("db_queries.get_npc_disposition", new_callable=AsyncMock, return_value="neutral"),
        patch("db_mutations.set_npc_disposition", new_callable=AsyncMock),
        patch("session_tools.publish_game_event", new_callable=AsyncMock),
    ):
        mock_conn = AsyncMock()
        mock_txn.return_value.__aenter__.return_value = mock_conn

        data = json.loads(await update_npc_disposition(context, npc_id="torin", delta=1, reason="test"))

        assert data["npc_id"] == "torin"
        assert data["previous"] == "neutral"
        assert data["new"] == "friendly"
