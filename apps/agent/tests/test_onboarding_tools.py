"""Tests for onboarding tools — advance_onboarding_beat."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from session_data import CompanionState, SessionData


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
    """advance_onboarding_beat tool tests."""

    @pytest.mark.asyncio
    @patch("onboarding_tools.db_mutations.set_player_flag", new_callable=AsyncMock)
    async def test_advance_beat_1_to_2(self, mock_set_player_flag):
        from onboarding_tools import advance_onboarding_beat

        ctx = _make_context(onboarding_beat=1)

        raw = await advance_onboarding_beat._func(ctx)
        assert isinstance(raw, str)
        result = json.loads(raw)

        assert result["beat"] == 2
        assert result["beat_name"] == "market"
        assert ctx.userdata.onboarding_beat == 2
        mock_set_player_flag.assert_awaited_once_with("player_1", "onboarding_beat", 2)

    @pytest.mark.asyncio
    @patch("onboarding_tools.db_mutations.set_player_flag", new_callable=AsyncMock)
    async def test_advance_beat_2_to_3(self, mock_set_player_flag):
        from onboarding_tools import advance_onboarding_beat

        ctx = _make_context(onboarding_beat=2)

        raw = await advance_onboarding_beat._func(ctx)
        assert isinstance(raw, str)
        result = json.loads(raw)

        assert result["beat"] == 3
        assert result["beat_name"] == "companion_meeting"
        assert ctx.userdata.onboarding_beat == 3

    @pytest.mark.asyncio
    @patch("onboarding_tools.db_mutations.set_player_flag", new_callable=AsyncMock)
    async def test_advance_beat_3_initializes_companion(self, mock_set_player_flag):
        """Advancing past beat 3 (companion meeting) initializes CompanionState."""
        from onboarding_tools import advance_onboarding_beat

        ctx = _make_context(onboarding_beat=3)

        raw = await advance_onboarding_beat._func(ctx)
        assert isinstance(raw, str)
        result = json.loads(raw)

        assert result["beat"] == 4
        assert result["beat_name"] == "kael_suggestion"
        # Companion should be initialized
        assert ctx.userdata.companion is not None
        assert ctx.userdata.companion.name == "Kael"
        assert ctx.userdata.companion.id == "companion_kael"
        # companion_met flag should be set in DB
        calls = mock_set_player_flag.await_args_list
        flag_names = [c.args[1] for c in calls]
        assert "companion_met" in flag_names
        assert "onboarding_beat" in flag_names

    @pytest.mark.asyncio
    @patch("onboarding_tools.db_mutations.set_player_flag", new_callable=AsyncMock)
    async def test_advance_beat_4_to_5(self, mock_set_player_flag):
        from onboarding_tools import advance_onboarding_beat

        ctx = _make_context(onboarding_beat=4)
        # Companion already set from beat 3
        ctx.userdata.companion = CompanionState(id="companion_kael", name="Kael")

        raw = await advance_onboarding_beat._func(ctx)
        assert isinstance(raw, str)
        result = json.loads(raw)

        assert result["beat"] == 5
        assert result["beat_name"] == "first_destination"

    @pytest.mark.asyncio
    @patch("onboarding_tools.db_mutations.set_player_flag", new_callable=AsyncMock)
    async def test_advance_beat_5_returns_city_agent_handoff(self, mock_set_player_flag):
        """Advancing past beat 5 returns (CityAgent, json) tuple for tool-return handoff."""
        from onboarding_tools import advance_onboarding_beat

        ctx = _make_context(onboarding_beat=5, location_id="accord_guild_hall")
        ctx.userdata.companion = CompanionState(id="companion_kael", name="Kael")

        raw = await advance_onboarding_beat._func(ctx)

        # Should be a tuple (Agent, json_str) for tool-return handoff
        assert isinstance(raw, tuple)
        agent, json_str = raw
        from city_agent import CityAgent

        assert isinstance(agent, CityAgent)
        result = json.loads(json_str)
        assert result["onboarding_complete"] is True
        # onboarding_beat should be cleared
        assert ctx.userdata.onboarding_beat is None
        # DB flag should be set to "complete"
        from onboarding_tools import ONBOARDING_COMPLETE

        mock_set_player_flag.assert_any_await("player_1", "onboarding_beat", ONBOARDING_COMPLETE)

    @pytest.mark.asyncio
    async def test_advance_when_not_onboarding_returns_error(self):
        from onboarding_tools import advance_onboarding_beat

        ctx = _make_context(onboarding_beat=1)
        ctx.userdata.onboarding_beat = None

        raw = await advance_onboarding_beat._func(ctx)
        assert isinstance(raw, str)
        result = json.loads(raw)

        assert "error" in result

    @pytest.mark.asyncio
    @patch("onboarding_tools.db_mutations.set_player_flag", new_callable=AsyncMock)
    async def test_advance_preserves_location(self, mock_set_player_flag):
        """Beat advancement doesn't change location."""
        from onboarding_tools import advance_onboarding_beat

        ctx = _make_context(onboarding_beat=1, location_id="accord_market_square")

        await advance_onboarding_beat._func(ctx)

        assert ctx.userdata.location_id == "accord_market_square"
