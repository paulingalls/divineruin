"""Player STT observability across the multiplayer input split."""

from unittest.mock import MagicMock, patch

import pytest
from livekit.agents import Agent, StopResponse, llm, stt
from livekit.agents.language import LanguageCode

from multiplayer_transcription import _TranscriberAgent


async def _no_audio():
    if False:
        yield None


def _final_event(text: str) -> stt.SpeechEvent:
    return stt.SpeechEvent(
        type=stt.SpeechEventType.FINAL_TRANSCRIPT,
        alternatives=[stt.SpeechData(language=LanguageCode("en"), text=text)],
    )


@pytest.mark.asyncio
async def test_raw_final_event_rides_with_the_authenticated_transcript():
    event = _final_event("I inspect the door")
    emitted = []

    async def upstream(_agent, _audio, _settings):
        yield event

    agent = _TranscriberAgent("player-two", 4, emitted.append, MagicMock(), stt=None)
    with patch.object(Agent.default, "stt_node", new=upstream):
        assert [item async for item in agent.stt_node(_no_audio(), MagicMock())] == [event]

    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(
            llm.ChatContext.empty(), llm.ChatMessage(role="user", content=["I inspect the door"])
        )

    assert emitted[0].speech_events == (event,)
