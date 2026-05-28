"""Intent handoff into/out of BlacksmithAgent (enter_blacksmith / conclude_blacksmith).

Mirrors the dispatch enter/conclude return-to-caller pattern (pre_blacksmith_agent_type
on SessionData), so control returns to whichever region agent the player was in.
enter_blacksmith lives on CITY_TOOLS only — blacksmiths are settlement NPCs.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from blacksmith_agent import BlacksmithAgent
from blacksmith_tools import _conclude_blacksmith_impl, _enter_blacksmith_impl
from city_agent import CityAgent
from session_data import SessionData


def _ctx(location_id: str = "accord_guild_hall", current_agent_type: str = "city") -> MagicMock:
    ctx = MagicMock()
    ctx.userdata = SessionData(player_id="player_1", location_id=location_id)
    ctx.session = MagicMock()
    current = MagicMock()
    current._agent_type = current_agent_type
    ctx.session.current_agent = current
    return ctx


class TestEnterBlacksmith:
    @pytest.mark.asyncio
    async def test_hands_off_to_blacksmith_agent(self):
        ctx = _ctx()
        result = await _enter_blacksmith_impl(ctx)
        assert isinstance(result, tuple), "enter_blacksmith should hand off"
        assert isinstance(result[0], BlacksmithAgent)

    @pytest.mark.asyncio
    async def test_stores_caller_region_for_return(self):
        ctx = _ctx(current_agent_type="city")
        await _enter_blacksmith_impl(ctx)
        assert ctx.userdata.pre_blacksmith_agent_type == "city"

    @pytest.mark.asyncio
    async def test_derives_region_from_location_when_caller_lacks_agent_type(self):
        # A non-region caller (no _agent_type) must NOT default to City silently —
        # derive the return region from the current location.
        ctx = _ctx(location_id="accord_market_row")
        ctx.session.current_agent._agent_type = None
        with patch(
            "blacksmith_tools.db_content_queries.get_location_region_type",
            new_callable=AsyncMock,
            return_value="city",
        ) as m:
            await _enter_blacksmith_impl(ctx)
        m.assert_awaited_once_with("accord_market_row")
        assert ctx.userdata.pre_blacksmith_agent_type == "city"


class TestConcludeBlacksmith:
    @pytest.mark.asyncio
    async def test_returns_to_stored_region_agent(self):
        ctx = _ctx(location_id="accord_guild_hall")
        ctx.userdata.pre_blacksmith_agent_type = "city"
        result = await _conclude_blacksmith_impl(ctx)
        assert isinstance(result, tuple)
        assert isinstance(result[0], CityAgent)
        assert ctx.userdata.pre_blacksmith_agent_type is None  # cleared

    @pytest.mark.asyncio
    async def test_fallback_derives_region_from_location(self):
        # pre_blacksmith unset: derive region from the current location, not a
        # hardcoded City (Wisdom: never silently default region to City).
        ctx = _ctx(location_id="greyvale_ruins_entrance")
        ctx.userdata.pre_blacksmith_agent_type = None
        with patch(
            "blacksmith_tools.db_content_queries.get_location_region_type",
            new_callable=AsyncMock,
            return_value="dungeon",
        ) as m:
            result = await _conclude_blacksmith_impl(ctx)
        m.assert_awaited_once_with("greyvale_ruins_entrance")
        from dungeon_agent import DungeonAgent

        assert isinstance(result[0], DungeonAgent)
