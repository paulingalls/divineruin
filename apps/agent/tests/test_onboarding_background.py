"""Tests for OnboardingBackgroundProcess — lightweight stall detection for beats 4-5."""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from session_data import CompanionState, SessionData


class TestNudgeData:
    """ONBOARDING_NUDGES data structure validation."""

    def test_nudges_defined_for_beat_4(self):
        from onboarding_background import ONBOARDING_NUDGES

        assert 4 in ONBOARDING_NUDGES
        assert len(ONBOARDING_NUDGES[4]) == 3

    def test_nudges_defined_for_beat_5(self):
        from onboarding_background import ONBOARDING_NUDGES

        assert 5 in ONBOARDING_NUDGES
        assert len(ONBOARDING_NUDGES[5]) == 2

    def test_no_nudges_for_beats_1_through_3(self):
        from onboarding_background import ONBOARDING_NUDGES

        for beat in (1, 2, 3):
            assert beat not in ONBOARDING_NUDGES


def _make_bg(
    onboarding_beat: int | None = 4,
    last_player_speech: float = 0.0,
    last_agent_speech_end: float = 0.0,
    companion: CompanionState | None = None,
) -> tuple:  # (OnboardingBackgroundProcess, SessionData, MagicMock)
    from onboarding_background import OnboardingBackgroundProcess

    sd = SessionData(
        player_id="test_player",
        location_id="accord_market_square",
        onboarding_beat=onboarding_beat,
    )
    sd.last_player_speech_time = last_player_speech
    sd.last_agent_speech_end = last_agent_speech_end
    if companion is not None:
        sd.companion = companion

    mock_session = MagicMock()
    mock_session.generate_reply = AsyncMock()
    bg = OnboardingBackgroundProcess(session=mock_session, session_data=sd)
    return bg, sd, mock_session


class TestCheckNudge:
    """OnboardingBackgroundProcess._check_nudge stall detection logic."""

    @pytest.mark.asyncio
    async def test_no_nudge_when_beat_below_4(self):
        bg, _, mock_session = _make_bg(onboarding_beat=2)
        await bg._check_nudge()
        mock_session.generate_reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_nudge_when_beat_is_none(self):
        bg, _, mock_session = _make_bg(onboarding_beat=None)
        await bg._check_nudge()
        mock_session.generate_reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_nudge_before_delay(self):
        now = time.time()
        bg, _, mock_session = _make_bg(
            onboarding_beat=4,
            last_player_speech=now - 10,  # 10s ago — too recent
        )
        await bg._check_nudge()
        mock_session.generate_reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_nudge_if_no_player_speech(self):
        bg, _, mock_session = _make_bg(
            onboarding_beat=4,
            last_player_speech=0.0,  # player hasn't spoken yet
        )
        await bg._check_nudge()
        mock_session.generate_reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_nudge_after_delay(self):
        from onboarding_background import NUDGE_DELAY_SECONDS, ONBOARDING_NUDGES

        now = time.time()
        bg, _, mock_session = _make_bg(
            onboarding_beat=4,
            last_player_speech=now - NUDGE_DELAY_SECONDS - 5,
        )
        await bg._check_nudge()
        mock_session.generate_reply.assert_called_once()
        call_kwargs = mock_session.generate_reply.call_args[1]
        assert call_kwargs["instructions"] == ONBOARDING_NUDGES[4][0]

    @pytest.mark.asyncio
    async def test_nudge_advances_index(self):
        from onboarding_background import ONBOARDING_NUDGES

        now = time.time()
        bg, _, mock_session = _make_bg(
            onboarding_beat=4,
            last_player_speech=now - 60,
        )
        # First nudge
        await bg._check_nudge()
        assert bg._hint_index == 1

        # Reset timing for second nudge
        bg._last_hint_time = now - 60
        await bg._check_nudge()
        assert bg._hint_index == 2
        assert mock_session.generate_reply.call_count == 2
        second_call = mock_session.generate_reply.call_args[1]
        assert second_call["instructions"] == ONBOARDING_NUDGES[4][1]

    @pytest.mark.asyncio
    async def test_beat_change_resets_index(self):
        now = time.time()
        bg, sd, _ = _make_bg(
            onboarding_beat=4,
            last_player_speech=now - 60,
        )
        # Deliver first nudge for beat 4
        await bg._check_nudge()
        assert bg._hint_index == 1

        # Beat changes to 5
        sd.onboarding_beat = 5
        bg._last_hint_time = now - 60
        await bg._check_nudge()
        assert bg._hint_index == 1  # reset to 0, then advanced to 1
        assert bg._last_active_beat == 5

    @pytest.mark.asyncio
    async def test_all_nudges_exhausted(self):
        from onboarding_background import ONBOARDING_NUDGES

        now = time.time()
        bg, _, mock_session = _make_bg(
            onboarding_beat=4,
            last_player_speech=now - 60,
        )
        bg._hint_index = len(ONBOARDING_NUDGES[4])  # past the end
        bg._last_active_beat = 4
        await bg._check_nudge()
        mock_session.generate_reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_baseline_considers_agent_speech_end(self):
        now = time.time()
        bg, _, mock_session = _make_bg(
            onboarding_beat=4,
            last_player_speech=now - 60,  # player silent 60s
            last_agent_speech_end=now - 5,  # but agent spoke 5s ago
        )
        await bg._check_nudge()
        mock_session.generate_reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_baseline_considers_last_hint_time(self):
        now = time.time()
        bg, _, mock_session = _make_bg(
            onboarding_beat=4,
            last_player_speech=now - 60,
        )
        bg._last_hint_time = now - 5  # hint delivered 5s ago
        bg._last_active_beat = 4
        await bg._check_nudge()
        mock_session.generate_reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_companion_speech_time_updated(self):
        now = time.time()
        companion = CompanionState(id="companion_kael", name="Kael", last_speech_time=0.0)
        bg, _, _ = _make_bg(
            onboarding_beat=4,
            last_player_speech=now - 60,
            companion=companion,
        )
        await bg._check_nudge()
        assert companion.last_speech_time > 0
