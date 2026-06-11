"""Tests for resolve_companion_errand on DispatchAgent (story-009).

resolve_companion_errand wraps the shared errand_resolution helper: it locks the
activity row FOR UPDATE, returns a worker-cached outcome without re-rolling, and
polls a 'resolving' row without ever holding the lock across a sleep. Failures
raise LiveKit ToolError (ADR 0002). The _*_impl seam takes injected mods. Split
from the dispatch tests (test_errand_tools_dispatch.py) to stay under the
500-line cap.
"""

import json
from contextlib import asynccontextmanager
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_db_mod

from errand_tools import _RESOLVE_POLL_ATTEMPTS, _resolve_companion_errand_impl

# Resolve drives errand_tools -> companion_relationship_queries.apply_errand_affinity (DB).
# Opt into the narrow rank/affinity stub (root conftest) to stay DB-free (story-007).
pytestmark = pytest.mark.usefixtures("stub_companion_errand_affinity_io")


def _resolve_now(iso="2026-05-22T12:00:00+00:00"):
    return datetime.fromisoformat(iso)


def _due_activity(resolve_at="2026-05-22T00:00:00+00:00", outcome=None):
    """An in-progress errand row already past its resolve_at by default."""
    return {
        "id": "activity_err123",
        "player_id": "player_1",
        "activity_type": "companion_errand",
        "status": "resolved" if outcome else "in_progress",
        "resolve_at": resolve_at,
        "outcome": outcome,
        "parameters": {"errand_type": "scout", "destination": "millhaven", "dc": 12},
    }


def _resolving_activity(outcome=None):
    """An errand the worker has CAS-claimed (status='resolving'); `outcome` is set
    once the worker writes it (Step B) while status is still 'resolving'."""
    return {
        "id": "activity_err123",
        "player_id": "player_1",
        "activity_type": "companion_errand",
        "status": "resolving",
        "resolve_at": "2026-05-22T00:00:00+00:00",
        "outcome": outcome,
        "parameters": {"errand_type": "scout", "destination": "millhaven", "dc": 12},
    }


async def _fake_resolve(_companion_data, parameters, **_):
    return {
        "tier": "success",
        "errand_type": parameters["errand_type"],
        "narrative_context": {"risk_outcome": "none"},
        "decision_options": [{"id": "thank", "label": "Thank them"}],
    }


class TestResolveCompanionErrand:
    @pytest.mark.asyncio
    async def test_returns_worker_outcome_shape(self):
        ctx = make_context()
        activity_mod = MagicMock()
        activity_mod.get_activity = AsyncMock(return_value=_due_activity())
        queries_mod = MagicMock()
        queries_mod.get_player = AsyncMock(
            return_value={"player_id": "player_1", "companion": {"id": "companion_kael", "name": "Kael"}}
        )
        mutations_mod = MagicMock()
        mutations_mod.update_activity = AsyncMock()

        result = json.loads(
            await _resolve_companion_errand_impl(
                ctx,
                "activity_err123",
                db_mod=make_db_mod()[0],
                activity_mod=activity_mod,
                queries_mod=queries_mod,
                mutations_mod=mutations_mod,
                resolve_fn=_fake_resolve,
                now_fn=_resolve_now,
            )
        )
        assert result["tier"] == "success"
        assert result["narrative_context"]["risk_outcome"] == "none"
        assert result["decision_options"][0]["id"] == "thank"

    @pytest.mark.asyncio
    async def test_persists_outcome_and_marks_resolved(self):
        """Resolving persists the rolled outcome + status so the worker skips it
        and never produces a second, divergent ending."""
        ctx = make_context()
        activity_mod = MagicMock()
        activity_mod.get_activity = AsyncMock(return_value=_due_activity())
        queries_mod = MagicMock()
        queries_mod.get_player = AsyncMock(
            return_value={"player_id": "player_1", "companion": {"id": "companion_kael"}}
        )
        mutations_mod = MagicMock()
        mutations_mod.update_activity = AsyncMock()

        await _resolve_companion_errand_impl(
            ctx,
            "activity_err123",
            db_mod=make_db_mod()[0],
            activity_mod=activity_mod,
            queries_mod=queries_mod,
            mutations_mod=mutations_mod,
            resolve_fn=_fake_resolve,
            now_fn=_resolve_now,
        )
        mutations_mod.update_activity.assert_awaited_once()
        _id, updates = mutations_mod.update_activity.await_args.args
        assert _id == "activity_err123"
        assert updates["status"] == "resolved"
        assert updates["outcome"]["tier"] == "success"

    @pytest.mark.asyncio
    async def test_locks_row_for_update_and_threads_conn(self):
        """Resource-row template: the row is fetched FOR UPDATE inside a transaction
        and the write is threaded through the same connection (concern 6b223681ec4f)."""
        ctx = make_context()
        mock_db, mock_conn = make_db_mod()
        activity_mod = MagicMock()
        activity_mod.get_activity = AsyncMock(return_value=_due_activity())
        queries_mod = MagicMock()
        queries_mod.get_player = AsyncMock(
            return_value={"player_id": "player_1", "companion": {"id": "companion_kael"}}
        )
        mutations_mod = MagicMock()
        mutations_mod.update_activity = AsyncMock()

        await _resolve_companion_errand_impl(
            ctx,
            "activity_err123",
            db_mod=mock_db,
            activity_mod=activity_mod,
            queries_mod=queries_mod,
            mutations_mod=mutations_mod,
            resolve_fn=_fake_resolve,
            now_fn=_resolve_now,
        )
        get_kwargs = activity_mod.get_activity.await_args.kwargs
        assert get_kwargs.get("for_update") is True
        assert get_kwargs.get("conn") is mock_conn
        assert mutations_mod.update_activity.await_args.kwargs.get("conn") is mock_conn

    @pytest.mark.asyncio
    async def test_already_resolved_returns_cached_no_reroll(self):
        """A row the worker already resolved returns its persisted outcome and
        never re-rolls."""
        ctx = make_context()
        cached = {"tier": "complication", "narrative_context": {"risk_outcome": "injured"}, "decision_options": []}
        activity_mod = MagicMock()
        activity_mod.get_activity = AsyncMock(return_value=_due_activity(outcome=cached))
        queries_mod = MagicMock()
        queries_mod.get_player = AsyncMock()
        mutations_mod = MagicMock()
        mutations_mod.update_activity = AsyncMock()
        resolve_fn = AsyncMock()

        result = json.loads(
            await _resolve_companion_errand_impl(
                ctx,
                "activity_err123",
                db_mod=make_db_mod()[0],
                activity_mod=activity_mod,
                queries_mod=queries_mod,
                mutations_mod=mutations_mod,
                resolve_fn=resolve_fn,
                now_fn=_resolve_now,
            )
        )
        assert result["tier"] == "complication"
        resolve_fn.assert_not_awaited()
        mutations_mod.update_activity.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_not_yet_due_raises_no_resolve(self):
        """An errand resolved before resolve_at passes raises rather than
        returning a zero-elapsed-time result."""
        ctx = make_context()
        activity_mod = MagicMock()
        activity_mod.get_activity = AsyncMock(return_value=_due_activity(resolve_at="2026-05-22T20:00:00+00:00"))
        mutations_mod = MagicMock()
        mutations_mod.update_activity = AsyncMock()
        resolve_fn = AsyncMock()

        with pytest.raises(ToolError, match="still out"):
            await _resolve_companion_errand_impl(
                ctx,
                "activity_err123",
                db_mod=make_db_mod()[0],
                activity_mod=activity_mod,
                queries_mod=MagicMock(),
                mutations_mod=mutations_mod,
                resolve_fn=resolve_fn,
                now_fn=_resolve_now,
            )
        resolve_fn.assert_not_awaited()
        mutations_mod.update_activity.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_still_resolving_after_window_polls_then_raises(self):
        """A row stuck in 'resolving' for the whole poll window still fails closed
        with the same ToolError — but only after re-reading it in a fresh
        transaction each attempt (poll-then-raise, never double-rolls)."""
        ctx = make_context()
        activity_mod = MagicMock()
        activity_mod.get_activity = AsyncMock(return_value=_resolving_activity())
        queries_mod = MagicMock()
        queries_mod.get_player = AsyncMock()
        mutations_mod = MagicMock()
        mutations_mod.update_activity = AsyncMock()
        resolve_fn = AsyncMock()
        sleep_fn = AsyncMock()

        with pytest.raises(ToolError, match="currently being resolved"):
            await _resolve_companion_errand_impl(
                ctx,
                "activity_err123",
                db_mod=make_db_mod()[0],
                activity_mod=activity_mod,
                queries_mod=queries_mod,
                mutations_mod=mutations_mod,
                resolve_fn=resolve_fn,
                now_fn=_resolve_now,
                sleep_fn=sleep_fn,
            )
        # Re-read in a fresh transaction every attempt; sleep between attempts only.
        assert activity_mod.get_activity.await_count == _RESOLVE_POLL_ATTEMPTS
        assert sleep_fn.await_count == _RESOLVE_POLL_ATTEMPTS - 1
        resolve_fn.assert_not_awaited()
        mutations_mod.update_activity.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_resolving_then_resolved_within_window_returns(self):
        """If the worker finishes mid-poll (writes its outcome while still
        'resolving', Step B), the tool returns that outcome without raising and
        without re-rolling — the worker's single roll is authoritative (ADR 0006)."""
        ctx = make_context()
        worker_outcome = {
            "tier": "success",
            "narrative_context": {"risk_outcome": "none"},
            "decision_options": [{"id": "thank", "label": "Thank them"}],
        }
        activity_mod = MagicMock()
        # First read: worker still resolving (no outcome). Second read: outcome landed.
        activity_mod.get_activity = AsyncMock(
            side_effect=[_resolving_activity(), _resolving_activity(outcome=worker_outcome)]
        )
        queries_mod = MagicMock()
        queries_mod.get_player = AsyncMock()
        mutations_mod = MagicMock()
        mutations_mod.update_activity = AsyncMock()
        resolve_fn = AsyncMock()
        sleep_fn = AsyncMock()

        result = json.loads(
            await _resolve_companion_errand_impl(
                ctx,
                "activity_err123",
                db_mod=make_db_mod()[0],
                activity_mod=activity_mod,
                queries_mod=queries_mod,
                mutations_mod=mutations_mod,
                resolve_fn=resolve_fn,
                now_fn=_resolve_now,
                sleep_fn=sleep_fn,
            )
        )
        assert result["tier"] == "success"
        assert activity_mod.get_activity.await_count == 2
        assert sleep_fn.await_count == 1
        resolve_fn.assert_not_awaited()
        mutations_mod.update_activity.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_resolving_poll_does_not_hold_lock_across_sleep(self):
        """The hard constraint: a FOR UPDATE transaction is never held across a
        sleep. Each re-read opens and closes its own transaction; the sleep runs
        with no transaction open."""
        mock_conn = MagicMock()
        open_txns = 0
        max_open_during_sleep = 0

        @asynccontextmanager
        async def tracking_txn():
            nonlocal open_txns
            open_txns += 1
            try:
                yield mock_conn
            finally:
                open_txns -= 1

        db_mod = MagicMock()
        db_mod.transaction = tracking_txn

        async def record_sleep(_seconds):
            nonlocal max_open_during_sleep
            max_open_during_sleep = max(max_open_during_sleep, open_txns)

        ctx = make_context()
        activity_mod = MagicMock()
        activity_mod.get_activity = AsyncMock(return_value=_resolving_activity())
        queries_mod = MagicMock()
        queries_mod.get_player = AsyncMock()
        mutations_mod = MagicMock()
        mutations_mod.update_activity = AsyncMock()

        with pytest.raises(ToolError, match="currently being resolved"):
            await _resolve_companion_errand_impl(
                ctx,
                "activity_err123",
                db_mod=db_mod,
                activity_mod=activity_mod,
                queries_mod=queries_mod,
                mutations_mod=mutations_mod,
                resolve_fn=AsyncMock(),
                now_fn=_resolve_now,
                sleep_fn=record_sleep,
            )
        assert max_open_during_sleep == 0  # no FOR UPDATE held across any sleep
        assert open_txns == 0  # every transaction closed

    @pytest.mark.asyncio
    async def test_unknown_errand_raises(self):
        ctx = make_context()
        activity_mod = MagicMock()
        activity_mod.get_activity = AsyncMock(return_value=None)
        with pytest.raises(ToolError):
            await _resolve_companion_errand_impl(
                ctx, "activity_missing", db_mod=make_db_mod()[0], activity_mod=activity_mod, queries_mod=MagicMock()
            )

    @pytest.mark.asyncio
    async def test_not_owned_raises(self):
        ctx = make_context()
        activity_mod = MagicMock()
        activity_mod.get_activity = AsyncMock(
            return_value={"id": "activity_err123", "player_id": "someone_else", "parameters": {}}
        )
        with pytest.raises(ToolError):
            await _resolve_companion_errand_impl(
                ctx, "activity_err123", db_mod=make_db_mod()[0], activity_mod=activity_mod, queries_mod=MagicMock()
            )
