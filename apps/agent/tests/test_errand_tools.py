"""Tests for the companion-errand agent tools on DispatchAgent (story-009).

dispatch_companion_errand validates (template, destination, blocked companion,
blocked danger combo, free slot) then creates an async_activities row;
resolve_companion_errand wraps the shared errand_resolution helper. Failures
raise LiveKit ToolError (ADR 0002). The _*_impl seams take injected mods.
"""

import json
import random
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import FIXED_NOW, make_context, make_db_mod

from errand_tools import _dispatch_companion_errand_impl, _resolve_companion_errand_impl

SCOUT_TEMPLATE = {
    "id": "scout",
    "name": "Scouting Mission",
    "duration_min_seconds": 14400,
    "duration_max_seconds": 28800,
    "valid_destinations": ["millhaven", "greyvale_ruins_entrance", "accord_dockside"],
    "blocked_companions": [],
}
SOCIAL_TEMPLATE = {
    "id": "social",
    "name": "Social Inquiry",
    "duration_min_seconds": 10800,
    "duration_max_seconds": 21600,
    "valid_destinations": ["millhaven"],
    "blocked_companions": ["companion_sable"],
}
# Crafted template that routes a blocked danger/errand combo through a valid
# destination (the real relationship template never lists a dangerous one).
RELATIONSHIP_AT_DANGER_TEMPLATE = {
    "id": "relationship",
    "name": "Build Relationship",
    "duration_min_seconds": 7200,
    "duration_max_seconds": 14400,
    "valid_destinations": ["greyvale_ruins_entrance"],
    "blocked_companions": [],
}


def _content(template, location):
    mod = MagicMock()
    mod.get_errand_template = AsyncMock(return_value=template)
    mod.get_location = AsyncMock(return_value=location)
    return mod


def _activity(companion_count=0):
    mod = MagicMock()
    mod.count_active_by_slot = AsyncMock(return_value={"training": 0, "crafting": 0, "companion": companion_count})
    return mod


def _mutations(activity_id="activity_err123"):
    mod = MagicMock()
    mod.create_async_activity = AsyncMock(return_value=activity_id)
    return mod


class TestDispatchCompanionErrand:
    @pytest.mark.asyncio
    async def test_happy_path_creates_row(self):
        ctx = make_context()
        mutations = _mutations("activity_err123")
        result = json.loads(
            await _dispatch_companion_errand_impl(
                ctx,
                "companion_kael",
                "scout",
                "millhaven",
                content_mod=_content(SCOUT_TEMPLATE, {"danger_level": 0}),
                activity_mod=_activity(0),
                mutations_mod=mutations,
                now_fn=lambda: FIXED_NOW,
                rng=random.Random(1),
            )
        )
        assert result["activity_id"] == "activity_err123"
        assert "resolve_at_estimate" in result
        assert result["errand_type"] == "scout"
        ctx.disallow_interruptions.assert_called_once()
        # Row data carries the async-worker contract fields.
        data = (
            mutations.create_async_activity.await_args.kwargs.get("activity_data")
            or (mutations.create_async_activity.await_args.args[1])
        )
        assert data["status"] == "in_progress"
        assert data["activity_type"] == "companion_errand"
        assert data["parameters"] == {"errand_type": "scout", "destination": "millhaven"}
        # Template's spec range is recorded on the row.
        assert data["duration_min_seconds"] == 14400
        assert data["duration_max_seconds"] == 28800
        # The sampled resolve_at duration falls within that range.
        sampled = datetime.fromisoformat(data["resolve_at"]) - FIXED_NOW
        assert timedelta(seconds=14400) <= sampled <= timedelta(seconds=28800)

    @pytest.mark.asyncio
    async def test_full_companion_slot_raises_no_row(self):
        ctx = make_context()
        mutations = _mutations()
        with pytest.raises(ToolError, match="errand"):
            await _dispatch_companion_errand_impl(
                ctx,
                "companion_kael",
                "scout",
                "millhaven",
                content_mod=_content(SCOUT_TEMPLATE, {"danger_level": 0}),
                activity_mod=_activity(1),
                mutations_mod=mutations,
            )
        mutations.create_async_activity.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_errand_type_raises(self):
        ctx = make_context()
        mutations = _mutations()
        with pytest.raises(ToolError):
            await _dispatch_companion_errand_impl(
                ctx,
                "companion_kael",
                "nonsense",
                "millhaven",
                content_mod=_content(None, {"danger_level": 0}),
                activity_mod=_activity(0),
                mutations_mod=mutations,
            )
        mutations.create_async_activity.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_invalid_destination_for_type_raises(self):
        ctx = make_context()
        mutations = _mutations()
        with pytest.raises(ToolError, match="destination"):
            await _dispatch_companion_errand_impl(
                ctx,
                "companion_kael",
                "scout",
                "narnia",
                content_mod=_content(SCOUT_TEMPLATE, {"danger_level": 0}),
                activity_mod=_activity(0),
                mutations_mod=mutations,
            )
        mutations.create_async_activity.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_blocked_companion_raises(self):
        ctx = make_context()
        mutations = _mutations()
        with pytest.raises(ToolError, match="companion_sable"):
            await _dispatch_companion_errand_impl(
                ctx,
                "companion_sable",
                "social",
                "millhaven",
                content_mod=_content(SOCIAL_TEMPLATE, {"danger_level": 0}),
                activity_mod=_activity(0),
                mutations_mod=mutations,
            )
        mutations.create_async_activity.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_malformed_danger_level_raises_toolerror_not_valueerror(self):
        """A typo'd danger_level surfaces a clean ToolError, not a raw ValueError."""
        ctx = make_context()
        mutations = _mutations()
        with pytest.raises(ToolError, match="danger level"):
            await _dispatch_companion_errand_impl(
                ctx,
                "companion_kael",
                "scout",
                "millhaven",
                content_mod=_content(SCOUT_TEMPLATE, {"danger_level": 99}),
                activity_mod=_activity(0),
                mutations_mod=mutations,
            )
        mutations.create_async_activity.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_blocked_danger_combo_raises(self):
        ctx = make_context()
        mutations = _mutations()
        with pytest.raises(ToolError):
            await _dispatch_companion_errand_impl(
                ctx,
                "companion_kael",
                "relationship",
                "greyvale_ruins_entrance",
                content_mod=_content(RELATIONSHIP_AT_DANGER_TEMPLATE, {"danger_level": 2}),
                activity_mod=_activity(0),
                mutations_mod=mutations,
            )
        mutations.create_async_activity.assert_not_awaited()


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


class TestDispatchToolRegistration:
    def test_dispatch_tools_within_strict_limit(self):
        from dispatch_agent import DISPATCH_TOOLS
        from llm_config import MAX_STRICT_TOOLS

        assert len(DISPATCH_TOOLS) <= MAX_STRICT_TOOLS

    def test_errand_tools_registered(self):
        from dispatch_agent import DISPATCH_TOOLS
        from errand_tools import dispatch_companion_errand, resolve_companion_errand

        assert dispatch_companion_errand in DISPATCH_TOOLS
        assert resolve_companion_errand in DISPATCH_TOOLS
