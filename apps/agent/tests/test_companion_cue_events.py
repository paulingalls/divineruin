"""Failure boundaries for companion-cue HUD publication."""

import asyncio
import logging
import time
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.rtc.participant import PublishDataError
from speech_handles import completed_handle

from background_process import BackgroundProcess
from bg_speech import PendingSpeech, SpeechPriority
from onboarding_background import OnboardingBackgroundProcess
from session_data import CompanionState, SessionData
from system_prompts import build_companion_cue


def _session_data() -> SessionData:
    companion = CompanionState(id="companion_sable", name="Sable")
    sd = SessionData(
        player_id="player_1",
        location_id="accord_guild_hall",
        companion=companion,
    )
    room = MagicMock()
    room.isconnected.return_value = True
    room.local_participant.publish_data = AsyncMock()
    sd.room = room
    return sd


def _queued_background(sd: SessionData) -> tuple[BackgroundProcess, MagicMock]:
    session = MagicMock()
    session.generate_reply = MagicMock(side_effect=lambda **_kwargs: completed_handle())
    background = BackgroundProcess(session, sd)
    background._speech_queue.append(
        PendingSpeech(
            SpeechPriority.IMPORTANT,
            build_companion_cue(cast(CompanionState, sd.companion), "reacts to the moment.", "steady"),
        )
    )
    return background, session


def _publisher(sd: SessionData) -> AsyncMock:
    return cast(AsyncMock, cast(Any, sd.room).local_participant.publish_data)


def _cue_error_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.name == "divineruin.companion_cue_events" and record.levelno == logging.ERROR
    ]


@pytest.mark.asyncio
async def test_publish_data_error_keeps_background_voice_and_timestamp(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sd = _session_data()
    failure = PublishDataError("cue rejected")
    _publisher(sd).side_effect = failure
    background, session = _queued_background(sd)

    with caplog.at_level(logging.ERROR, logger="divineruin.companion_cue_events"):
        await background._deliver_speech()

    session.generate_reply.assert_called_once()
    assert cast(CompanionState, sd.companion).last_speech_time > 0
    records = _cue_error_records(caplog)
    assert len(records) == 1
    assert records[0].exc_info is not None
    assert records[0].exc_info[1] is failure


@pytest.mark.asyncio
async def test_runtime_error_escapes_background_before_voice() -> None:
    sd = _session_data()
    failure = RuntimeError("publish defect")
    _publisher(sd).side_effect = failure
    background, session = _queued_background(sd)

    with pytest.raises(RuntimeError) as raised:
        await background._deliver_speech()

    assert raised.value is failure
    session.generate_reply.assert_not_called()


@pytest.mark.asyncio
async def test_publish_data_error_keeps_onboarding_loop_alive(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sd = _session_data()
    sd.onboarding_beat = 4
    sd.last_player_speech_time = time.time() - 60
    failure = PublishDataError("cue rejected")
    publishes = 0

    async def publish(*_args: object, **_kwargs: object) -> None:
        nonlocal publishes
        publishes += 1
        if publishes == 1:
            raise failure

    second_reply = asyncio.Event()

    def reply(**_kwargs: object):
        if session.generate_reply.call_count >= 2:
            second_reply.set()
        return completed_handle()

    _publisher(sd).side_effect = publish
    session = MagicMock()
    session.generate_reply = MagicMock(side_effect=reply)
    background = OnboardingBackgroundProcess(session, sd)

    try:
        with (
            patch("onboarding_background.POLL_INTERVAL_SECONDS", 0),
            patch("onboarding_background.NUDGE_DELAY_SECONDS", 0),
            caplog.at_level(logging.ERROR, logger="divineruin.companion_cue_events"),
        ):
            background.start()
            await asyncio.wait_for(second_reply.wait(), timeout=2)
            assert background._task is not None
            assert not background._task.done()
    finally:
        await background.stop()

    assert session.generate_reply.call_count >= 2
    records = _cue_error_records(caplog)
    assert len(records) == 1
    assert records[0].exc_info is not None
    assert records[0].exc_info[1] is failure


@pytest.mark.asyncio
async def test_runtime_error_ends_onboarding_loop_before_voice() -> None:
    sd = _session_data()
    sd.onboarding_beat = 4
    sd.last_player_speech_time = time.time() - 60
    failure = RuntimeError("publish defect")
    _publisher(sd).side_effect = failure
    session = MagicMock()
    session.generate_reply = MagicMock()
    background = OnboardingBackgroundProcess(session, sd)

    with patch("onboarding_background.POLL_INTERVAL_SECONDS", 0):
        background.start()
        assert background._task is not None
        with pytest.raises(RuntimeError) as raised:
            await asyncio.wait_for(background._task, timeout=2)

    assert raised.value is failure
    session.generate_reply.assert_not_called()
