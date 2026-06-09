"""Tests for prune_training_cycle_accruals (Phase 6 sprint-010 / story-007).

training_cycle_accruals is a write-only idempotency ledger (debt b20815f92023): one row per
skill_practice completion, never read except by the INSERT...ON CONFLICT claim. It grew
unbounded (debt 8336cc9c9d03). prune_training_cycle_accruals deletes rows older than the
retention window; the worker calls it every maintenance cycle. Rows only guard retries bounded
by the activity resolving_at timeout (minutes/hours), so a 7-day-old row can never be re-claimed.

Per ADR 0003 the unit lane is mock-only (real SQL runs in the acceptance/testcontainer lane);
these tests pin the DELETE SQL shape, the parameterized window, the default retention, and the
"deletes nothing when nothing is expired" idempotency contract (story-007 AC #2) against a mock
connection — deterministic and lane-independent.
"""

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
        # AC #2 (idempotency): a run with no expired rows deletes nothing, so re-running is a no-op.
        conn = _mock_conn("DELETE 0")
        assert await db_training.prune_training_cycle_accruals(conn=conn) == 0
