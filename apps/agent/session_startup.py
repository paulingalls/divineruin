import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from livekit.agents import AgentSession, inference, room_io, stt
from livekit.plugins import deepgram

from base_agent import BaseGameAgent, _make_tts
from gameplay_llm import create_gameplay_llm
from multiplayer_input import MultiplayerInput
from multiplayer_transcription import MultiParticipantTranscriber
from participant_lifecycle import PartyLifecycle, _setup_party_join
from session_data import SessionData


def _primary_room_options(userdata: SessionData, *, audio_input: bool) -> room_io.RoomOptions:
    """Link RoomIO to the primary player and leave a drop to _setup_reconnection's grace."""
    return room_io.RoomOptions(
        participant_identity=userdata.primary_player_id,
        audio_input=audio_input,
        text_input=False,
        close_on_disconnect=False,
    )


def gameplay_room_options(userdata: SessionData) -> room_io.RoomOptions:
    # Gameplay speech reaches the DM through MultiParticipantTranscriber's per-player sessions,
    # so this session takes no room audio of its own — it would hear the primary twice.
    return _primary_room_options(userdata, audio_input=False)


def solo_room_options(userdata: SessionData) -> room_io.RoomOptions:
    # Creation and onboarding run before any transcriber exists, so this session is the only
    # thing listening: without room audio the player talks and the DM never answers.
    return _primary_room_options(userdata, audio_input=True)


@dataclass
class GameplayInputOwner:
    lifecycle: PartyLifecycle
    transcriber: MultiParticipantTranscriber
    input: MultiplayerInput

    async def aclose(self) -> None:
        results = await asyncio.gather(
            self.input.aclose(),
            self.transcriber.aclose(),
            self.lifecycle.aclose(),
            return_exceptions=True,
        )
        failures = [result for result in results if isinstance(result, BaseException)]
        if failures:
            raise BaseExceptionGroup("multiplayer input cleanup failed", failures)


def _observe_through_current_agent(session: AgentSession) -> Callable[[tuple[stt.SpeechEvent, ...], str, str], None]:
    """Fork player speech to whichever agent holds the floor, resolved per turn.

    An enter_combat handoff swaps the agent, and on_exit closes the outgoing agent's
    transcript logger and stops its affect analyzer: a bound method captured at startup
    would keep writing player lines into a logger with no handlers for the rest of the fight.
    """

    def observe(events: tuple[stt.SpeechEvent, ...], player_id: str, transcript: str) -> None:
        cast(BaseGameAgent, session.current_agent).observe_player_speech(events, player_id, transcript)

    return observe


async def start_gameplay_session(
    room: Any,
    session: AgentSession,
    agent: Any,
    userdata: SessionData,
) -> GameplayInputOwner:
    speech_ready = asyncio.Event()
    lifecycle = _setup_party_join(room, userdata, agent_session=session, speech_ready=speech_ready)
    await session.start(room=room, agent=agent, room_options=gameplay_room_options(userdata))
    speech_ready.set()
    transcriber = MultiParticipantTranscriber(
        room,
        stt=deepgram.STT(model="nova-3", language="en"),
        authorizer=lifecycle.authorize,
    )
    multiplayer_input = MultiplayerInput(
        transcriber,
        lifecycle,
        session,
        userdata,
        observe_player_speech=_observe_through_current_agent(session),
    )
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
        llm=create_gameplay_llm(model),
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
