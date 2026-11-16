from unittest.mock import MagicMock

import pytest
from livekit.agents.llm import ToolError

from session_data import SessionData


def _make_context(onboarding_beat: int = 1, location_id: str = "accord_market_square"):
    ctx = MagicMock()
    sd = SessionData(
        player_id="player_1",
        location_id=location_id,
        onboarding_beat=onboarding_beat,
    )
    ctx.userdata = sd
    ctx.session = MagicMock()
    return ctx


class TestAdvanceOnboardingBeat:
    @pytest.mark.asyncio
    async def test_advance_when_not_onboarding_returns_error(self):
        from onboarding_tools import advance_onboarding_beat

        ctx = _make_context(onboarding_beat=1)
        ctx.userdata.onboarding_beat = None

        with pytest.raises(ToolError, match="Not in onboarding mode"):
            await advance_onboarding_beat._func(ctx)
