"""The tts_instance_callback seam the replay runner meters Inworld TTS through."""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

from livekit.agents.tts import TTS

from base_agent import BaseGameAgent
from voices import VoiceConfig


def _stub_tts() -> MagicMock:
    tts = MagicMock()
    stream = MagicMock()
    stream.__aenter__ = AsyncMock(return_value=stream)
    stream.__aexit__ = AsyncMock()

    async def frames():
        yield MagicMock(frame=MagicMock())

    stream.__aiter__ = lambda self: frames()
    tts.synthesize.return_value = stream
    return tts


def _segment(character: str) -> MagicMock:
    segment = MagicMock()
    segment.character = character
    segment.emotion = "neutral"
    segment.text = f"{character} speaks."
    return segment


async def test_every_voice_switch_hands_its_tts_instance_to_the_observer():
    observed: list[TTS] = []
    agent = BaseGameAgent(instructions="test", tools=[], tts_instance_callback=observed.append)

    async def text() -> AsyncIterator[str]:
        yield "unused"

    async def segments():
        yield _segment("narrator")
        yield _segment("merchant_tobias")

    instances = [_stub_tts(), _stub_tts()]
    voices = [
        VoiceConfig(voice="narrator-voice", speaking_rate=1.0),
        VoiceConfig(voice="tobias-voice", speaking_rate=1.0),
    ]
    with (
        patch("base_agent.parse_dialogue_stream", return_value=segments()),
        patch("base_agent.get_voice_config", side_effect=voices),
        patch("base_agent._make_tts", side_effect=instances) as make_tts,
    ):
        async for _ in agent.tts_node(text(), MagicMock()):
            pass

    # One instance per distinct voice, each surfaced so its Inworld metrics can be metered.
    assert make_tts.call_count == 2
    assert observed == instances
