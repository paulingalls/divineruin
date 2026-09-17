"""Tests for OnboardingBackgroundProcess — lightweight stall detection for beats 4-5."""

import asyncio
import logging
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents import Agent, AgentSession
from livekit.agents.voice import SpeechHandle
from livekit.agents.voice.agent_activity import AgentActivity
from speech_handles import completed_handle

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
    sd.companion = companion or CompanionState(id="companion_kael", name="Kael")

    mock_session = MagicMock()
    mock_session.generate_reply = MagicMock(side_effect=lambda **_kwargs: completed_handle())
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
        assert ONBOARDING_NUDGES[4][0][0] in call_kwargs["instructions"]

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
        assert ONBOARDING_NUDGES[4][1][0] in second_call["instructions"]

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


@pytest.mark.asyncio
async def test_running_process_logs_check_failure(caplog):
    bg, _, _ = _make_bg()
    failure = RuntimeError("nudge broke")
    with (
        patch("onboarding_background.POLL_INTERVAL_SECONDS", 0),
        patch.object(bg, "_check_nudge", new_callable=AsyncMock, side_effect=failure),
        caplog.at_level(logging.ERROR, logger="divineruin.onboarding_background"),
    ):
        bg.start()
        with pytest.raises(RuntimeError, match="nudge broke") as raised:
            await asyncio.wait_for(bg._task, timeout=2)
        await asyncio.sleep(0)

    records = [
        record
        for record in caplog.records
        if record.name == "divineruin.onboarding_background" and record.levelno == logging.ERROR
    ]
    assert len(records) == 1
    assert records[0].message == "Onboarding background process failed"
    assert records[0].exc_info is not None
    assert records[0].exc_info[1] is raised.value


async def _run_until_second_check(bg, sd):
    real_check = bg._check_nudge
    second_check = asyncio.Event()
    check_count = 0

    async def check():
        nonlocal check_count
        check_count += 1
        if check_count == 2:
            sd.last_player_speech_time = time.time()
            bg._stop = True
            second_check.set()
        await real_check()

    with (
        patch("onboarding_background.POLL_INTERVAL_SECONDS", 0),
        patch.object(bg, "_check_nudge", new_callable=AsyncMock, side_effect=check),
    ):
        bg.start()
        waiter = asyncio.create_task(second_check.wait())
        try:
            done, _ = await asyncio.wait({waiter, bg._task}, timeout=2, return_when=asyncio.FIRST_COMPLETED)
            assert done
            if bg._task in done:
                await bg._task
            await waiter
            await bg._task
        finally:
            waiter.cancel()
            await bg.stop()


def _delivery_records(caplog, level):
    return [
        record
        for record in caplog.records
        if record.name == "divineruin.onboarding_background" and record.levelno == level
    ]


@pytest.mark.parametrize(
    ("state", "message"),
    [
        ("not-running", "AgentSession isn't running"),
        ("closing", "AgentSession is closing, cannot use generate_reply()"),
    ],
)
@pytest.mark.asyncio
async def test_real_session_shutdown_state_warns_and_loop_survives(caplog, state, message):
    session = AgentSession(max_tool_steps=5)
    if state == "closing":
        session._activity = AgentActivity(Agent(instructions="plain"), session)
    bg, sd, _ = _make_bg(last_player_speech=time.time() - 60)
    bg._session = session
    companion = sd.companion

    with caplog.at_level(logging.WARNING, logger="divineruin.onboarding_background"):
        await _run_until_second_check(bg, sd)

    warnings = _delivery_records(caplog, logging.WARNING)
    assert len(warnings) == 1
    assert message in warnings[0].getMessage()
    assert _delivery_records(caplog, logging.ERROR) == []
    assert bg._hint_index == 0
    assert bg._last_hint_time == 0
    assert companion is not None and companion.last_speech_time == 0


@pytest.mark.asyncio
async def test_other_generate_reply_runtimeerror_escapes():
    bg, _, session = _make_bg(last_player_speech=time.time() - 60)
    failure = RuntimeError("reply invariant broke")
    session.generate_reply.side_effect = failure

    with pytest.raises(RuntimeError) as raised:
        await bg._check_nudge()

    assert raised.value is failure


class FalsyFailure(Exception):
    """A failure that is falsy — the only shape that tells `is not None` apart from a truth test."""

    def __bool__(self):
        return False


def _in_flight_handle(failure: BaseException) -> SpeechHandle:
    """A handle still speaking: it finishes only on the next pass of the loop.

    Until then `exception()` raises InvalidStateError, so a delivery that reads the handle
    without awaiting it ends the loop instead of warning.
    """
    handle = SpeechHandle.create()
    asyncio.get_running_loop().call_soon(handle._mark_done, failure)
    return handle


@pytest.mark.asyncio
async def test_delivery_awaits_the_handle_before_reading_its_failure(caplog):
    bg, _, session = _make_bg(last_player_speech=time.time() - 60)
    session.generate_reply.side_effect = lambda **_kwargs: _in_flight_handle(OSError("late failure"))

    with caplog.at_level(logging.WARNING, logger="divineruin.onboarding_background"):
        await bg._check_nudge()

    warnings = _delivery_records(caplog, logging.WARNING)
    assert len(warnings) == 1
    assert "late failure" in warnings[0].getMessage()
    assert bg._hint_index == 0


@pytest.mark.asyncio
async def test_failed_handle_warns_and_loop_survives(caplog):
    bg, sd, session = _make_bg(last_player_speech=time.time() - 60)
    failure = FalsyFailure("generation failed")
    session.generate_reply.side_effect = lambda **_kwargs: completed_handle(failure)
    companion = sd.companion

    with caplog.at_level(logging.WARNING, logger="divineruin.onboarding_background"):
        await _run_until_second_check(bg, sd)

    warnings = _delivery_records(caplog, logging.WARNING)
    assert len(warnings) == 1
    assert "generation failed" in warnings[0].getMessage()
    assert _delivery_records(caplog, logging.ERROR) == []
    assert bg._hint_index == 0
    assert bg._last_hint_time == 0
    assert companion is not None and companion.last_speech_time == 0


def test_onboarding_imports_the_single_session_unavailable_policy():
    agent_dir = Path(__file__).parents[1]
    sources = {path.name: path.read_text() for path in agent_dir.glob("*.py")}
    assert (
        "from background_process import GENERATE_REPLY_SESSION_UNAVAILABLE_ARGS" in sources["onboarding_background.py"]
    )
    for message in (
        "AgentSession isn't running",
        "AgentSession is closing, cannot use generate_reply()",
    ):
        assert sum(source.count(message) for source in sources.values()) == 1
