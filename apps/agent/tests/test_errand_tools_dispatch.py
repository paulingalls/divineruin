"""Tests for dispatch_companion_errand on DispatchAgent (story-009).

dispatch_companion_errand validates (template, destination, blocked companion,
blocked danger combo, free slot) then creates an async_activities row. Failures
raise LiveKit ToolError (ADR 0002). The _*_impl seam takes injected mods. Split
from the resolve-path tests (test_errand_tools_resolve.py) to stay under the
500-line cap; the DispatchAgent registration smoke test rides with dispatch.
"""

import json
import random
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import FIXED_NOW, make_context

from errand_tools import _dispatch_companion_errand_impl

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
