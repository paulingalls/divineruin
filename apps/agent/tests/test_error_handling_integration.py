"""Integration tests for database error handling with transactions."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from session_data import SessionData
from tools import award_xp, update_npc_disposition


@pytest.mark.asyncio
async def test_award_xp_connection_error_returns_json_error():
    """When DB connection fails, tool should return user-friendly JSON error."""
    context = MagicMock()
    session = SessionData(
        room=MagicMock(),
        event_bus=MagicMock(),
        player_id="test_player",
        location_id="test_location",
    )
    context.userdata = session

    # Simulate connection failure during transaction
    with patch("db.transaction") as mock_txn:
        mock_txn.side_effect = ConnectionError("Database unreachable")

        result = await award_xp(context, amount=100, reason="test")
        data = json.loads(result)

        assert data["success"] is False
        assert "error" in data
        assert "trouble accessing" in data["error"].lower()
        assert "guidance" in data


@pytest.mark.asyncio
async def test_update_disposition_timeout_returns_json_error():
    """When DB times out, tool should return user-friendly JSON error."""
    context = MagicMock()
    session = SessionData(
        room=MagicMock(),
        event_bus=MagicMock(),
        player_id="test_player",
        location_id="test_location",
    )
    context.userdata = session

    # Simulate timeout during transaction
    # Must also mock db.get_npc since it's called before db.transaction
    with patch("db.transaction") as mock_txn, patch("db_queries.get_npc", new_callable=AsyncMock) as mock_get_npc:
        mock_get_npc.return_value = {"id": "torin", "name": "Torin", "default_disposition": "neutral"}
        mock_txn.side_effect = TimeoutError("Query took too long")

        result = await update_npc_disposition(context, npc_id="torin", delta=1, reason="test")
        data = json.loads(result)

        assert data["success"] is False
        assert "error" in data
        assert "longer than expected" in data["error"].lower()


@pytest.mark.asyncio
async def test_transaction_rollback_prevents_partial_state():
    """When transaction fails mid-way, no events should be published."""
    context = MagicMock()
    session = SessionData(
        room=MagicMock(),
        event_bus=MagicMock(),
        player_id="test_player",
        location_id="test_location",
    )
    context.userdata = session

    initial_events = len(session.recent_events)

    # Simulate transaction that fails after read but before write
    with patch("db.transaction") as mock_txn, patch("db_queries.get_player") as mock_get:
        mock_conn = AsyncMock()
        mock_txn.return_value.__aenter__.return_value = mock_conn

        # get_player succeeds but transaction raises error
        mock_get.return_value = {
            "player_id": "test_player",
            "xp": 100,
            "level": 1,
        }
        mock_conn.execute.side_effect = ConnectionError("DB write failed")

        result = await award_xp(context, amount=50, reason="test")
        data = json.loads(result)

        # Should get error response
        assert data["success"] is False

        # Session should not have recorded event (rollback)
        assert len(session.recent_events) == initial_events


@pytest.mark.asyncio
async def test_successful_mutation_after_error():
    """After error, subsequent successful call should work normally."""
    context = MagicMock()
    session = SessionData(
        room=MagicMock(),
        event_bus=MagicMock(),
        player_id="test_player",
        location_id="test_location",
    )
    context.userdata = session

    # First call fails
    with patch("db.transaction") as mock_txn:
        mock_txn.side_effect = ConnectionError("Temporary failure")
        result1 = await award_xp(context, amount=100, reason="test")
        data1 = json.loads(result1)
        assert data1["success"] is False

    # Second call succeeds (mocked)
    with (
        patch("db.transaction") as mock_txn,
        patch("db_queries.get_player") as mock_get,
        patch("db_mutations.update_player_xp"),
        patch("tools.publish_game_event", new_callable=AsyncMock),
    ):
        mock_conn = AsyncMock()
        mock_txn.return_value.__aenter__.return_value = mock_conn
        mock_get.return_value = {
            "player_id": "test_player",
            "xp": 100,
            "level": 1,
        }

        result2 = await award_xp(context, amount=100, reason="test")
        data2 = json.loads(result2)

        # Should succeed
        assert "success" not in data2 or data2.get("success") is not False
        assert "new_xp" in data2
