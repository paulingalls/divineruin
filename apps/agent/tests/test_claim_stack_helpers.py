"""Behavior tests for the shared CAS claim-lifecycle helper (claim_stack_helpers).

The async-worker/e2e callers exercise this indirectly; these pin the primitive
itself — entering the patch stack and asserting the wired-up lifecycle every
caller depends on, so a future edit can't silently change a target or default.
"""

import pytest
from claim_stack_helpers import mock_txn, patch_claim_stack

import async_worker


@pytest.mark.asyncio
async def test_mock_txn_yields_the_conn():
    sentinel = object()
    async with mock_txn(sentinel) as conn:
        assert conn is sentinel


def test_returns_conn_plus_four_patches():
    mock_conn, txn_p, get_p, claim_p, revert_p = patch_claim_stack({"id": "a"})
    # mark_resolved awaits conn.execute, so the txn conn's execute must be awaitable.
    assert hasattr(mock_conn.execute, "assert_awaited")
    for p in (txn_p, get_p, claim_p, revert_p):
        assert hasattr(p, "__enter__")


@pytest.mark.asyncio
async def test_patches_wire_up_the_worker_lifecycle():
    activity = {"id": "activity_xyz", "status": "in_progress"}
    mock_conn, txn_p, get_p, claim_p, revert_p = patch_claim_stack(activity)
    with txn_p, get_p, claim_p, revert_p:
        # FOR-UPDATE re-fetch returns the activity dict the helper was given.
        assert await async_worker.db_activity_queries.get_activity("activity_xyz") == activity
        # claim defaults to True (claim succeeds).
        assert await async_worker.claim_resolving("activity_xyz", conn=mock_conn) is True
        # revert is a noop AsyncMock the caller can assert on.
        await async_worker.revert_claim_safe("activity_xyz")
        async_worker.revert_claim_safe.assert_awaited_once()
        # db.transaction() yields the same mock conn (so mark_resolved's await lands on it).
        async with async_worker.db.transaction() as conn:
            assert conn is mock_conn


@pytest.mark.asyncio
async def test_claim_returns_false_exercises_lost_claim_branch():
    mock_conn, _txn, _get, claim_p, _revert = patch_claim_stack({"id": "a"}, claim_returns=False)
    with claim_p:
        assert await async_worker.claim_resolving("a", conn=mock_conn) is False
