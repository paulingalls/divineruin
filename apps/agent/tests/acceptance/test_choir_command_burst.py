"""The short recorded transport stimulus must produce separate owned STT turns."""

import pytest
from acceptance.choir_capstone_voice import CHOIR_COMMAND_SPEECH, BurstSTT
from acceptance.multiplayer_voice._harness import SpeechFixture
from livekit.agents import stt


async def recognize(frames):
    stream = BurstSTT().stream()
    try:
        for frame in frames:
            stream.push_frame(frame)
        stream.end_input()
        return [event async for event in stream]
    finally:
        await stream.aclose()


@pytest.mark.asyncio
async def test_recorded_bursts_produce_two_complete_turns():
    frames = CHOIR_COMMAND_SPEECH.frames()
    assert sum(frame.duration for frame in frames) == pytest.approx(0.96)
    events = await recognize(frames * 2)
    assert [event.type for event in events] == [
        stt.SpeechEventType.START_OF_SPEECH,
        stt.SpeechEventType.FINAL_TRANSCRIPT,
        stt.SpeechEventType.END_OF_SPEECH,
    ] * 2
    assert [event.alternatives[0].text for event in events if event.alternatives] == [
        "capstone turn 1",
        "capstone turn 2",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["missing-voice", "short-voice", "missing-separation"])
async def test_threshold_faults_cannot_produce_two_complete_turns(fault):
    frames = CHOIR_COMMAND_SPEECH.frames()
    if fault == "missing-voice":
        frames = frames[18:]
    elif fault == "short-voice":
        frames = [*frames[:10], *frames[18:]]
    else:
        frames = frames[:18]
    events = await recognize(frames * 2)
    assert len([event for event in events if event.type == stt.SpeechEventType.END_OF_SPEECH]) < 2
    if fault != "missing-separation":
        assert not events


@pytest.mark.parametrize("frames", [[], "silence"])
def test_command_recording_requires_reachable_voiced_audio(frames, monkeypatch):
    if frames == "silence":
        frames = CHOIR_COMMAND_SPEECH.frames()[18:]
    monkeypatch.setattr(SpeechFixture, "frames", lambda self: frames)
    with pytest.raises(ValueError, match="no voiced audio"):
        CHOIR_COMMAND_SPEECH.frames()
