import asyncio
import time
from dataclasses import dataclass
from typing import Any

from livekit.agents import AgentSession, inference, room_io
from livekit.plugins import anthropic, deepgram

from base_agent import _make_tts
from multiplayer_input import MultiplayerInput
from multiplayer_transcription import MultiParticipantTranscriber
from participant_lifecycle import PartyLifecycle, _setup_party_join
from session_data import SessionData


def gameplay_room_options() -> room_io.RoomOptions:
    return room_io.RoomOptions(audio_input=False, text_input=False)


@dataclass
class GameplayInputOwner:
    lifecycle: PartyLifecycle
    transcriber: MultiParticipantTranscriber
    input: MultiplayerInput

    async def aclose(self) -> None:
        results = await asyncio.gather(self.input.aclose(), self.transcriber.aclose(), return_exceptions=True)
        failures = [result for result in results if isinstance(result, BaseException)]
        if failures:
            raise BaseExceptionGroup("multiplayer input cleanup failed", failures)


async def start_gameplay_session(
    room: Any,
    session: AgentSession,
    agent: Any,
    userdata: SessionData,
) -> GameplayInputOwner:
    lifecycle = _setup_party_join(room, userdata)
    await session.start(room=room, agent=agent, room_options=gameplay_room_options())
    transcriber = MultiParticipantTranscriber(
        room,
        stt=deepgram.STT(model="nova-3", language="en"),
        authorizer=lifecycle.authorize,
    )
    multiplayer_input = MultiplayerInput(transcriber, lifecycle, session, userdata)
    owner = GameplayInputOwner(lifecycle, transcriber, multiplayer_input)
    userdata.multiplayer_owner = owner
    transcriber.start()
    multiplayer_input.start()

    def close_multiplayer_input(_event: Any) -> None:
        if userdata.multiplayer_close_task is None:
            userdata.multiplayer_close_task = asyncio.create_task(owner.aclose())

    session.on("close", close_multiplayer_input)
    return owner


def _register_speech_end_tracking(session: AgentSession) -> None:
    @session.on("agent_state_changed")
    def _on_agent_state(ev):
        if ev.old_state == "speaking":
            session.userdata.last_agent_speech_end = time.time()


def _make_agent_session(model: str, userdata: SessionData) -> AgentSession:
    session = AgentSession(
        stt=deepgram.STT(model="nova-3", language="en"),
        # Strict schemas remain disabled because the live Anthropic API rejects three of the
        # six agents on aggregate grammar size even though their inspectable schemas fit.
        llm=anthropic.LLM(model=model, temperature=0.8, caching="ephemeral", _strict_tool_schema=False),
        tts=_make_tts(),
        vad=inference.VAD(model="silero", min_silence_duration=0.5),
        # LiveKit selects the full audio turn detector in cloud/dev and its local fallback
        # elsewhere; audio cues keep natural pauses from ending a turn.
        turn_handling={
            "turn_detection": inference.TurnDetector(),
            "endpointing": {"min_delay": 0.5},
            "interruption": {"enabled": True},
        },
        # LiveKit permits max_tool_steps + 1 consecutive calls and silently narrates when the
        # cap is reached. Five leaves one step beyond the longest designed chain.
        max_tool_steps=5,
        userdata=userdata,
    )
    _register_speech_end_tracking(session)
    return session
