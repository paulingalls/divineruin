"""Tests for the award_xp mutation tool (mocked DB + room)."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import (
    GUILD_PLAYER as SAMPLE_PLAYER,
)
from sample_fixtures import (
    make_context as _make_context,
)
from sample_fixtures import (
    make_mock_room as _make_mock_room,
)
from sample_fixtures import (
    mock_txn as _mock_txn,
)

import event_types as E
from progression_tools import _award_xp_impl


class TestAwardXp:
    @pytest.mark.asyncio
    async def test_awards_xp(self):
        mock_conn = MagicMock()
        mock_db = MagicMock()
        mock_db.transaction = lambda: _mock_txn(mock_conn)
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
        mock_mutations = MagicMock()
        mock_mutations.update_player_xp = AsyncMock()
        ctx = _make_context()
        result = json.loads(
            await _award_xp_impl(
                ctx, 50, "defeated goblin", db_mod=mock_db, mutations=mock_mutations, queries=mock_queries
            )
        )
        assert result["amount"] == 50
        assert result["new_xp"] == 50
        assert result["leveled_up"] is False
        mock_mutations.update_player_xp.assert_called_once_with("player_1", 50, 1, conn=mock_conn)

    @pytest.mark.asyncio
    async def test_level_up(self):
        mock_conn = MagicMock()
        mock_db = MagicMock()
        mock_db.transaction = lambda: _mock_txn(mock_conn)
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(return_value={**SAMPLE_PLAYER, "xp": 250})
        mock_mutations = MagicMock()
        mock_mutations.update_player_xp = AsyncMock()
        ctx = _make_context()
        result = json.loads(
            await _award_xp_impl(
                ctx, 100, "quest complete", db_mod=mock_db, mutations=mock_mutations, queries=mock_queries
            )
        )
        assert result["new_xp"] == 350
        assert result["new_level"] == 2
        assert result["leveled_up"] is True
        mock_mutations.update_player_xp.assert_called_once_with("player_1", 350, 2, conn=mock_conn)

    @pytest.mark.asyncio
    async def test_negative_amount(self):
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _award_xp_impl(ctx, -10, "cheat", db_mod=MagicMock(), mutations=MagicMock(), queries=MagicMock())

    @pytest.mark.asyncio
    async def test_zero_amount(self):
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _award_xp_impl(ctx, 0, "nothing", db_mod=MagicMock(), mutations=MagicMock(), queries=MagicMock())

    @pytest.mark.asyncio
    async def test_missing_player(self):
        mock_conn = MagicMock()
        mock_db = MagicMock()
        mock_db.transaction = lambda: _mock_txn(mock_conn)
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(return_value=None)
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _award_xp_impl(ctx, 50, "test", db_mod=mock_db, mutations=MagicMock(), queries=mock_queries)

    @pytest.mark.asyncio
    async def test_publishes_event(self):
        mock_conn = MagicMock()
        mock_db = MagicMock()
        mock_db.transaction = lambda: _mock_txn(mock_conn)
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
        mock_mutations = MagicMock()
        mock_mutations.update_player_xp = AsyncMock()
        room = _make_mock_room()
        ctx = _make_context(room=room)
        await _award_xp_impl(ctx, 50, "test", db_mod=mock_db, mutations=mock_mutations, queries=mock_queries)
        room.local_participant.publish_data.assert_called_once()
        call_data = json.loads(room.local_participant.publish_data.call_args[0][0])
        assert call_data["type"] == E.XP_AWARDED
        assert call_data["amount"] == 50

    @pytest.mark.asyncio
    async def test_max_level_no_level_up(self):
        mock_conn = MagicMock()
        mock_db = MagicMock()
        mock_db.transaction = lambda: _mock_txn(mock_conn)
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(return_value={**SAMPLE_PLAYER, "level": 20, "xp": 355000})
        mock_mutations = MagicMock()
        mock_mutations.update_player_xp = AsyncMock()
        ctx = _make_context()
        result = json.loads(
            await _award_xp_impl(ctx, 1000, "bonus", db_mod=mock_db, mutations=mock_mutations, queries=mock_queries)
        )
        assert result["new_level"] == 20
        assert result["leveled_up"] is False
        assert result["new_xp"] == 356000
