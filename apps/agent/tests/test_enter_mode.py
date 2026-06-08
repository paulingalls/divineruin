"""The `enter_mode` verb dispatcher (M5, ADR 0007, Verbs & Stages §4/§10).

`enter_mode(mode, ...)` folds start_combat / enter_dispatch / enter_blacksmith into
one mode-discriminated handoff verb. These tests cover the NEW dispatcher primitive
in isolation — the three underlying `_*_impl` handoffs keep their own suites
(test_combat/*, test_dispatch_handoff, test_blacksmith_handoff) and are patched here
so we assert delegation + fail-loud guards, not the handoff bodies.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents.llm import ToolError

from mode_tools import _enter_mode_impl


def _ctx() -> MagicMock:
    return MagicMock(name="run_context")


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
