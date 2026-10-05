from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import make_context

from mode_tools import _enter_mode_impl


def _ctx() -> MagicMock:
    return make_context()


class TestEnterModeDelegation:
    @pytest.mark.asyncio
    async def test_combat_delegates_with_encounter_args(self):
        ctx = _ctx()
        sentinel = ("combat-agent", "{}")
        with patch("mode_tools._start_combat_impl", new_callable=AsyncMock, return_value=sentinel) as m:
            result = await _enter_mode_impl(ctx, "combat", "goblin_ambush", "they leap from the reeds")
        m.assert_awaited_once_with(ctx, "goblin_ambush", "they leap from the reeds")
        assert result is sentinel

    @pytest.mark.asyncio
    async def test_dispatch_delegates(self):
        ctx = _ctx()
        sentinel = ("dispatch-agent", "{}")
        with patch("mode_tools._enter_dispatch_impl", new_callable=AsyncMock, return_value=sentinel) as m:
            result = await _enter_mode_impl(ctx, "dispatch")
        m.assert_awaited_once_with(ctx)
        assert result is sentinel

    @pytest.mark.asyncio
    async def test_blacksmith_delegates(self):
        ctx = _ctx()
        sentinel = ("blacksmith-agent", "{}")
        with patch("mode_tools._enter_blacksmith_impl", new_callable=AsyncMock, return_value=sentinel) as m:
            result = await _enter_mode_impl(ctx, "blacksmith")
        m.assert_awaited_once_with(ctx)
        assert result is sentinel


class TestEnterModeFailLoud:
    @pytest.mark.asyncio
    async def test_combat_without_encounter_id_fails_loud(self):
        ctx = _ctx()
        with patch("mode_tools._start_combat_impl", new_callable=AsyncMock) as m:
            with pytest.raises(ToolError, match="encounter_id"):
                await _enter_mode_impl(ctx, "combat", "", "they leap out")
        m.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_mode_fails_loud_listing_valid_modes(self):
        ctx = _ctx()
        with pytest.raises(ToolError, match="combat, dispatch, blacksmith"):
            await _enter_mode_impl(ctx, "wizardry")
