import logging
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.rtc.participant import PublishDataError
from speech_handles import completed_handle

from background_process import BackgroundProcess
from bg_speech import PendingSpeech, SpeechPriority
from companion_prompts import build_companion_cue
from session_data import CompanionState, SessionData


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
