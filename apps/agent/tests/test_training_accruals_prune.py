"""Accrual rows guard bounded worker retries; ancient rows cannot be reclaimed and need not remain forever."""

from unittest.mock import AsyncMock

import pytest

import db_training


def _mock_conn(status: str = "DELETE 0") -> AsyncMock:
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=status)
    return conn


class TestPruneSql:
    @pytest.mark.asyncio
    async def test_deletes_by_age_with_parameterized_window(self):
        conn = _mock_conn("DELETE 3")
        deleted = await db_training.prune_training_cycle_accruals(retention_days=30, conn=conn)
        assert deleted == 3
        sql, *args = conn.execute.await_args.args
        assert "DELETE FROM training_cycle_accruals" in sql
        assert "make_interval(days => $1)" in sql
        assert args[0] == 30  # window is parameterized, not string-interpolated

    @pytest.mark.asyncio
    async def test_default_retention_is_7_days(self):
        conn = _mock_conn("DELETE 0")
        await db_training.prune_training_cycle_accruals(conn=conn)
        _, *args = conn.execute.await_args.args
        assert args[0] == 7

    @pytest.mark.asyncio
    async def test_returns_zero_when_nothing_expired(self):
        conn = _mock_conn("DELETE 0")
        assert await db_training.prune_training_cycle_accruals(conn=conn) == 0
