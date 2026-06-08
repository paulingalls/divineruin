"""Tests for the async_worker_claim CAS helpers: claim / mark / revert / stale-reset."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestClaimResolving:
    @pytest.mark.asyncio
    async def test_claims_when_status_in_progress(self):
        """CAS succeeds when row is in_progress; returns True and stamps resolving_at."""
        from async_worker_claim import claim_resolving

        mock_conn = MagicMock()
        mock_conn.fetchval = AsyncMock(return_value="activity_abc")
        ok = await claim_resolving("activity_abc", mock_conn)
        assert ok is True
        sql = mock_conn.fetchval.call_args[0][0]
        assert "data->>'status' = 'in_progress'" in sql
        assert "resolving" in sql
        assert "resolving_at" in sql
        assert "NOW()" in sql
        assert "RETURNING id" in sql

    @pytest.mark.asyncio
    async def test_fails_when_status_already_resolving(self):
        """No row matches the in_progress predicate -> RETURNING yields None -> False."""
        from async_worker_claim import claim_resolving

        mock_conn = MagicMock()
        mock_conn.fetchval = AsyncMock(return_value=None)
        ok = await claim_resolving("activity_abc", mock_conn)
        assert ok is False

    @pytest.mark.asyncio
    async def test_fails_when_status_resolved(self):
        """Row in terminal state: CAS predicate fails -> RETURNING yields None -> False."""
        from async_worker_claim import claim_resolving

        mock_conn = MagicMock()
        mock_conn.fetchval = AsyncMock(return_value=None)
        ok = await claim_resolving("activity_abc", mock_conn)
        assert ok is False


class TestMarkResolved:
    @pytest.mark.asyncio
    async def test_strips_resolving_at_and_merges_updates_when_resolving(self):
        """Terminal write must strip transient resolving_at AND resolve_attempts +
        merge new fields in one statement (no orphan internal field leaks through
        the raw `...data` egress), CAS-guarded on status='resolving'."""
        from async_worker_claim import mark_resolved

        mock_conn = MagicMock()
        mock_conn.fetchval = AsyncMock(return_value="activity_abc")
        applied = await mark_resolved(
            "activity_abc",
            {"status": "resolved", "narration_audio_url": "/audio/a.mp3"},
            mock_conn,
        )
        assert applied is True
        sql = mock_conn.fetchval.call_args[0][0]
        # Strip resolving_at AND resolve_attempts, then merge the updates jsonb — one
        # write, no orphan internal field leaks through the raw `...data` egress.
        assert "data - 'resolving_at' - 'resolve_attempts'" in sql
        assert "|| $2::jsonb" in sql
        # CAS guard: only a row still in 'resolving' is marked resolved — a row the
        # stale sweep already reverted to in_progress is not clobbered.
        assert "data->>'status' = 'resolving'" in sql
        assert "RETURNING id" in sql
        payload = mock_conn.fetchval.call_args[0][2]
        import json as _json

        parsed = _json.loads(payload)
        assert parsed["status"] == "resolved"
        assert parsed["narration_audio_url"] == "/audio/a.mp3"

    @pytest.mark.asyncio
    async def test_returns_false_when_row_no_longer_resolving(self):
        """If the row was reset/advanced off 'resolving' (e.g. stale sweep), the CAS
        predicate fails -> RETURNING yields None -> False, and nothing is clobbered."""
        from async_worker_claim import mark_resolved

        mock_conn = MagicMock()
        mock_conn.fetchval = AsyncMock(return_value=None)
        applied = await mark_resolved("activity_abc", {"status": "resolved"}, mock_conn)
        assert applied is False


class TestRevertClaim:
    @pytest.mark.asyncio
    async def test_reverts_resolving_to_in_progress_and_increments_attempts(self):
        from async_worker_claim import revert_claim

        mock_conn = MagicMock()
        mock_conn.fetchval = AsyncMock(return_value=1)
        await revert_claim("activity_abc", mock_conn)
        sql = mock_conn.fetchval.call_args[0][0]
        # WHERE-guarded: only flips rows that are currently 'resolving'.
        assert "data->>'status' = 'resolving'" in sql
        # Strips resolving_at and sets status back to in_progress.
        assert "'resolving_at'" in sql
        assert '"status": "in_progress"' in sql
        # Increments a resolve_attempts counter in the same write (ops visibility
        # into a persistently-failing TTS retry loop).
        assert "resolve_attempts" in sql
        assert "COALESCE" in sql
        assert "RETURNING" in sql

    @pytest.mark.asyncio
    async def test_no_op_when_not_resolving(self):
        """WHERE guard prevents the UPDATE; fetchval yields None — must not raise."""
        from async_worker_claim import revert_claim

        mock_conn = MagicMock()
        mock_conn.fetchval = AsyncMock(return_value=None)
        await revert_claim("activity_abc", mock_conn)
        mock_conn.fetchval.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_warns_when_attempts_cross_threshold(self):
        """At/above RESOLVE_ATTEMPT_WARN_THRESHOLD reverts, log a warning so a stuck
        retry loop (e.g. poisoned cached segments failing TTS forever) is visible."""
        import async_worker_claim

        mock_conn = MagicMock()
        mock_conn.fetchval = AsyncMock(return_value=async_worker_claim.RESOLVE_ATTEMPT_WARN_THRESHOLD)
        with patch.object(async_worker_claim.logger, "warning") as mock_warn:
            await async_worker_claim.revert_claim("activity_abc", mock_conn)
        mock_warn.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_warn_below_threshold(self):
        import async_worker_claim

        mock_conn = MagicMock()
        mock_conn.fetchval = AsyncMock(return_value=1)
        with patch.object(async_worker_claim.logger, "warning") as mock_warn:
            await async_worker_claim.revert_claim("activity_abc", mock_conn)
        mock_warn.assert_not_called()


class TestResetStaleResolving:
    @pytest.mark.asyncio
    async def test_resets_rows_past_threshold(self):
        """Rows with status='resolving' AND resolving_at older than threshold get reset."""
        import async_worker_claim

        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[{"id": "stale_1"}, {"id": "stale_2"}])
        with patch.object(async_worker_claim.db, "get_pool", return_value=mock_pool):
            count = await async_worker_claim.reset_stale_resolving(threshold_seconds=900)
        assert count == 2
        sql = mock_pool.fetch.call_args[0][0]
        assert "data->>'status' = 'resolving'" in sql
        assert "resolving_at" in sql
        # Threshold parameterized via $1, not string-interpolated.
        assert "$1" in sql

    @pytest.mark.asyncio
    async def test_fresh_resolving_rows_not_reset(self):
        """If no rows are past threshold, nothing returns -> count 0."""
        import async_worker_claim

        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[])
        with patch.object(async_worker_claim.db, "get_pool", return_value=mock_pool):
            count = await async_worker_claim.reset_stale_resolving(threshold_seconds=900)
        assert count == 0
