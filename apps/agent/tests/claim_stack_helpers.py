"""Shared CAS claim-lifecycle test helpers (async-worker resolve race, story-004).

worker_suite/test_single_activity_resolution.py and test_async_e2e.py both mock the same claim/transaction
lifecycle that _resolve_single_activity drives: a db.transaction yielding a mock
conn, a get_activity FOR-UPDATE re-fetch, claim_resolving, and revert_claim_safe.
Extracted here to kill the duplicated copies before a third lands (concern
d55602722fee). The db.transaction() stub itself is the canonical mock_txn in
sample_fixtures.py (reused here); this module owns only the CAS-specific stack.
Flat-module convention matches sample_fixtures.py / training_config_fixture.py.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from sample_fixtures import mock_txn


def patch_claim_stack(activity_dict: dict, claim_returns: bool = True):
    """Build the CAS claim-lifecycle patch stack for async_worker.

    Returns (mock_conn, txn_patch, get_activity_patch, claim_patch, revert_patch).
    The caller wraps the four patch context managers with `with` alongside its
    own LLM/TTS mocks. mock_conn.execute is an AsyncMock because mark_resolved
    awaits conn.execute on the txn conn. `claim_returns` toggles the
    claim_resolving result (False exercises the lost-claim branch).
    """
    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock()
    txn_patch = patch("async_worker.db.transaction", lambda: mock_txn(mock_conn))
    get_activity_patch = patch(
        "async_worker.db_activity_queries.get_activity",
        new_callable=AsyncMock,
        return_value=activity_dict,
    )
    claim_patch = patch(
        "async_worker.claim_resolving",
        new_callable=AsyncMock,
        return_value=claim_returns,
    )
    revert_patch = patch("async_worker.revert_claim_safe", new_callable=AsyncMock)
    return mock_conn, txn_patch, get_activity_patch, claim_patch, revert_patch
