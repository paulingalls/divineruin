"""Intent handoff into/out of DispatchAgent (enter_dispatch / conclude_dispatch).

Complements the location-route handoff in test_training_agent.py. Mirrors the
combat start_combat/end_combat return-to-caller pattern (pre_dispatch_agent_type).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from city_agent import CITY_TOOLS, CityAgent
from dispatch_agent import DISPATCH_TOOLS, DispatchAgent
from dispatch_tools import _conclude_dispatch_impl, _enter_dispatch_impl, conclude_dispatch
from dungeon_agent import DUNGEON_TOOLS
from llm_config import MAX_STRICT_TOOLS
from mode_tools import enter_mode
from session_data import SessionData
from wilderness_agent import WILDERNESS_TOOLS


def _ctx(location_id: str = "accord_guild_hall", current_agent_type: str = "city") -> MagicMock:
    ctx = MagicMock()
    ctx.userdata = SessionData(player_id="player_1", location_id=location_id)
    ctx.session = MagicMock()
    current = MagicMock()
    current._agent_type = current_agent_type
    ctx.session.current_agent = current
    return ctx


class TestEnterDispatch:
    @pytest.mark.asyncio
    async def test_hands_off_to_dispatch_agent(self):
        ctx = _ctx()
        result = await _enter_dispatch_impl(ctx)
        assert isinstance(result, tuple), "enter_dispatch should hand off"
        assert isinstance(result[0], DispatchAgent)

    @pytest.mark.asyncio
    async def test_stores_caller_region_for_return(self):
        ctx = _ctx(current_agent_type="wilderness")
        await _enter_dispatch_impl(ctx)
        assert ctx.userdata.pre_dispatch_agent_type == "wilderness"

    @pytest.mark.asyncio
    async def test_derives_region_from_location_when_caller_lacks_agent_type(self):
        # A non-region caller (no _agent_type) must NOT default to City — derive the
        # return region from the current location so a non-city hall routes back right.
        ctx = _ctx(location_id="greyvale_ruins_entrance")
        ctx.session.current_agent._agent_type = None
        with patch(
            "dispatch_tools.db_content_queries.get_location_region_type",
            new_callable=AsyncMock,
            return_value="dungeon",
        ) as m:
            await _enter_dispatch_impl(ctx)
        m.assert_awaited_once_with("greyvale_ruins_entrance")
        assert ctx.userdata.pre_dispatch_agent_type == "dungeon"


class TestConcludeDispatch:
    @pytest.mark.asyncio
    async def test_returns_to_stored_region_agent(self):
        ctx = _ctx(location_id="accord_guild_hall")
        ctx.userdata.pre_dispatch_agent_type = "city"
        result = await _conclude_dispatch_impl(ctx)
        assert isinstance(result, tuple)
        assert isinstance(result[0], CityAgent)
        assert ctx.userdata.pre_dispatch_agent_type is None  # cleared

    @pytest.mark.asyncio
    async def test_fallback_derives_region_from_location(self):
        # pre_dispatch unset (e.g. reached via the location route): derive region
        # from the current location, not a hardcoded City.
        ctx = _ctx(location_id="greyvale_ruins_entrance")
        ctx.userdata.pre_dispatch_agent_type = None
        with patch(
            "dispatch_tools.db_content_queries.get_location_region_type",
            new_callable=AsyncMock,
            return_value="dungeon",
        ) as m:
            result = await _conclude_dispatch_impl(ctx)
        m.assert_awaited_once_with("greyvale_ruins_entrance")
        from dungeon_agent import DungeonAgent

        assert isinstance(result[0], DungeonAgent)


class TestIntentToolRegistration:
    def test_enter_mode_in_region_agents(self):
        # Dispatch entry now folds into the enter_mode verb (M5); all three region
        # agents hold it.
        assert enter_mode in CITY_TOOLS
        assert enter_mode in WILDERNESS_TOOLS
        assert enter_mode in DUNGEON_TOOLS

    def test_conclude_dispatch_in_dispatch_tools(self):
        assert conclude_dispatch in DISPATCH_TOOLS

    def test_region_agents_within_ceiling(self):
        assert len(CITY_TOOLS) <= MAX_STRICT_TOOLS
        assert len(WILDERNESS_TOOLS) <= MAX_STRICT_TOOLS
        assert len(DUNGEON_TOOLS) <= MAX_STRICT_TOOLS
        assert len(DISPATCH_TOOLS) <= MAX_STRICT_TOOLS
