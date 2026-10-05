"""Mock connections check SQL construction, not increment arithmetic."""

from unittest.mock import AsyncMock, patch

import pytest

import player_session


class TestHydratePlayerSession:
    async def test_increments_session_count_via_atomic_update_returning(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = {"session_count": 1}
        count = await player_session.hydrate_player_session("p1", conn=conn)

        sql, *params = conn.fetchrow.call_args.args
        assert "UPDATE players" in sql
        assert "jsonb_set" in sql
        assert "'{session_count}'" in sql  # top-level key beside {resonance}
        assert "COALESCE" in sql  # absent key defaults to 0 before the +1
        assert "+ 1" in sql
        assert "RETURNING" in sql  # the new count comes back in the same round-trip
        assert params == ["p1"]
        assert count == 1

    async def test_returns_the_db_computed_count_at_n(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = {"session_count": 6}
        count = await player_session.hydrate_player_session("p1", conn=conn)
        assert count == 6

    async def test_does_not_touch_other_pools(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = {"session_count": 1}
        await player_session.hydrate_player_session("p1", conn=conn)
        sql, *_ = conn.fetchrow.call_args.args
        assert "{resonance" not in sql and "{hp" not in sql and "{focus" not in sql

    async def test_fails_loud_when_player_row_missing(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = None
        with pytest.raises(ValueError):
            await player_session.hydrate_player_session("ghost", conn=conn)

    async def test_falls_back_to_shared_pool_when_conn_omitted(self):
        pool = AsyncMock()
        pool.fetchrow.return_value = {"session_count": 1}
        with patch.object(player_session.db, "get_pool", AsyncMock(return_value=pool)):
            count = await player_session.hydrate_player_session("p1")
        assert count == 1
        pool.fetchrow.assert_awaited_once()
