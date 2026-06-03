"""Tests for resolve_due_activities and the per-outcome resolution gates."""

from unittest.mock import AsyncMock, patch

import pytest
from worker_suite._samples import SAMPLE_ACTIVITY, SAMPLE_PLAYER

from async_worker import _resolve_one_outcome, resolve_due_activities


class TestResolveDueActivities:
    @pytest.mark.asyncio
    async def test_returns_zero_when_no_due_activities(self):
        with (
            patch("async_worker.db_activity_queries.get_due_activities", new_callable=AsyncMock, return_value=[]),
            patch("async_worker._backfill_progress_snippets", new_callable=AsyncMock),
        ):
            count = await resolve_due_activities()

        assert count == 0

    @pytest.mark.asyncio
    async def test_resolves_due_activities(self):
        with (
            patch(
                "async_worker.db_activity_queries.get_due_activities",
                new_callable=AsyncMock,
                return_value=[SAMPLE_ACTIVITY],
            ),
            patch("async_worker._resolve_single_activity", new_callable=AsyncMock) as mock_resolve,
            patch("async_worker._backfill_progress_snippets", new_callable=AsyncMock),
            patch("async_worker.generate_world_news", new_callable=AsyncMock),
        ):
            count = await resolve_due_activities()

        assert count == 1
        mock_resolve.assert_awaited_once_with(SAMPLE_ACTIVITY)

    @pytest.mark.asyncio
    async def test_continues_on_individual_failure(self):
        activities = [
            {**SAMPLE_ACTIVITY, "id": "act_1"},
            {**SAMPLE_ACTIVITY, "id": "act_2"},
        ]

        call_count = 0

        async def mock_resolve(activity):
            nonlocal call_count
            call_count += 1
            if activity["id"] == "act_1":
                raise RuntimeError("Transient failure")

        with (
            patch(
                "async_worker.db_activity_queries.get_due_activities", new_callable=AsyncMock, return_value=activities
            ),
            patch("async_worker._resolve_single_activity", side_effect=mock_resolve),
            patch("async_worker._backfill_progress_snippets", new_callable=AsyncMock),
            patch("async_worker.generate_world_news", new_callable=AsyncMock),
        ):
            count = await resolve_due_activities()

        assert call_count == 2
        assert count == 1  # Only act_2 succeeded


class TestResolveOneOutcomeGates:
    """story-005: the resolution gates must produce a failure OUTCOME (not raise) so
    the worker doesn't revert-and-reraise into an infinite retry loop; but ABSENT
    captured gate params must fail loud."""

    @pytest.mark.asyncio
    async def test_crafting_gate_failure_resolves_to_failure_without_raise(self):
        activity = {
            **SAMPLE_ACTIVITY,
            "parameters": {
                **SAMPLE_ACTIVITY["parameters"],
                "tainted_materials": True,
                "crafting_tier": "trained",  # sub-Expert working tainted -> gate fails
            },
        }
        outcome = await _resolve_one_outcome(activity, SAMPLE_PLAYER)
        assert outcome is not None
        assert outcome["tier"] == "failure"
        assert outcome["narrative_context"]["gate"] == "tainted_expert"

    @pytest.mark.asyncio
    async def test_crafting_absent_gate_param_raises(self):
        # A pre-backfill in-flight row missing a captured gate param must fail loud.
        activity = {
            **SAMPLE_ACTIVITY,
            "parameters": {k: v for k, v in SAMPLE_ACTIVITY["parameters"].items() if k != "workspace_access"},
        }
        with pytest.raises(ValueError, match="workspace_access"):
            await _resolve_one_outcome(activity, SAMPLE_PLAYER)
