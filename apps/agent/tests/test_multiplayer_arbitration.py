from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass, field

import pytest
from livekit.agents import Agent, AgentSession, StopResponse, llm

import multiplayer_transcription as transcription
from multiplayer_input import MultiplayerInput
from multiplayer_transcription import (
    AuthenticatedTranscript,
    MultiParticipantTranscriber,
    _TranscriberAgent,
)


class TranscriptSource:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[AuthenticatedTranscript] = asyncio.Queue()

    async def receive(self) -> AuthenticatedTranscript:
        return await self.queue.get()


class Lifecycle:
    def is_authorized(self, _identity: str, _generation: int) -> bool:
        return True

    def require_authorized(self, _identity: str, _generation: int) -> None:
        pass

    async def wait_until_revoked(self, _identity: str, _generation: int) -> None:
        await asyncio.Future()


class ActorData:
    def __init__(self) -> None:
        self.actor: str | None = None

    @contextmanager
    def _bind_authenticated_actor(self, identity: str, _generation: int, _validator):
        assert self.actor is None
        self.actor = identity
        try:
            yield
        finally:
            self.actor = None


class Reply:
    def __init__(self, actor_data: ActorData, actors: list[str], *, gated: bool = False) -> None:
        self.actor_data = actor_data
        self.actors = actors
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.interrupt_calls: list[bool] = []
        if not gated:
            self.release.set()

    async def _wait(self) -> None:
        assert self.actor_data.actor is not None
        self.actors.append(self.actor_data.actor)
        self.started.set()
        await self.release.wait()

    def __await__(self):
        return self._wait().__await__()

    def interrupt(self, *, force: bool = False):
        self.interrupt_calls.append(force)
        self.release.set()
        return self

    def exception(self):
        return None


class Session:
    def __init__(self, actor_data: ActorData, *, gate_first: bool = False) -> None:
        self.actor_data = actor_data
        self.gate_first = gate_first
        self.calls: list[str] = []
        self.actors: list[str] = []
        self.handles: list[Reply] = []
        # The real Agent, because deliver_player_turn runs its per-turn hook before replying.
        self.current_agent = Agent(instructions="arbitration double")

    def generate_reply(self, *, user_input: llm.ChatMessage, chat_ctx: llm.ChatContext) -> Reply:
        assert chat_ctx is not None
        self.calls.append(user_input.text_content or "")
        handle = Reply(self.actor_data, self.actors, gated=self.gate_first and not self.handles)
        self.handles.append(handle)
        return handle


async def test_complete_turns_wait_for_the_active_reply_and_rebind_the_actor() -> None:
    source = TranscriptSource()
    actor_data = ActorData()
    session = Session(actor_data, gate_first=True)
    owner = MultiplayerInput(source, Lifecycle(), session, actor_data)
    owner.start()

    source.queue.put_nowait(AuthenticatedTranscript("player-two", "second marker", 2))
    source.queue.put_nowait(AuthenticatedTranscript("player-one", "first marker", 1))
    async with asyncio.timeout(1):
        while not session.handles or not session.handles[0].started.is_set():
            await asyncio.sleep(0)

    assert session.calls == ["second marker"]
    assert session.actors == ["player-two"]
    assert session.handles[0].interrupt_calls == []

    session.handles[0].release.set()
    async with asyncio.timeout(1):
        while len(session.actors) != 2 or actor_data.actor is not None:
            await asyncio.sleep(0)

    assert session.calls == ["second marker", "first marker"]
    assert session.actors == ["player-two", "player-one"]
    assert actor_data.actor is None
    await owner.aclose()


async def test_solo_turn_starts_without_a_following_input() -> None:
    source = TranscriptSource()
    actor_data = ActorData()
    session = Session(actor_data)
    owner = MultiplayerInput(source, Lifecycle(), session, actor_data)
    owner.start()

    source.queue.put_nowait(AuthenticatedTranscript("player-one", "solo marker", 1))
    async with asyncio.timeout(1):
        while not session.handles or not session.handles[0].started.is_set():
            await asyncio.sleep(0)

    assert session.calls == ["solo marker"]
    assert session.actors == ["player-one"]
    await owner.aclose()


def message(text: str) -> llm.ChatMessage:
    return llm.ChatMessage(role="user", content=[text], extra={"speaker": "speaker-0"})


def fail_unexpected(error: BaseException) -> None:
    pytest.fail(str(error))


async def test_diarization_label_cannot_replace_authenticated_track_identity() -> None:
    emitted: list[AuthenticatedTranscript] = []
    agents = (
        _TranscriberAgent("player-one", 1, emitted.append, fail_unexpected, None),
        _TranscriberAgent("player-two", 2, emitted.append, fail_unexpected, None),
    )

    for agent, text in zip(agents, ("first marker", "second marker"), strict=True):
        with pytest.raises(StopResponse):
            await agent.on_user_turn_completed(llm.ChatContext.empty(), message(text))

    assert emitted == [
        AuthenticatedTranscript("player-one", "first marker", 1),
        AuthenticatedTranscript("player-two", "second marker", 2),
    ]


@dataclass
class Room:
    remote_participants: dict[str, object] = field(default_factory=dict)

    def on(self, _event: str, _callback) -> None:
        pass

    def off(self, _event: str, _callback) -> None:
        pass


async def authorize(_identity: str) -> int:
    return 1


async def receive(manager: MultiParticipantTranscriber):
    return await asyncio.wait_for(manager.receive(), 1)


async def emit(agent: _TranscriberAgent, text: str) -> None:
    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(llm.ChatContext.empty(), message(text))


async def test_queue_rejects_excess_speech_and_surfaces_failures_while_full() -> None:
    manager = MultiParticipantTranscriber(Room(), stt=None, authorizer=authorize)
    agent = _TranscriberAgent("player-two", 7, manager._emit_transcript, fail_unexpected, None)

    for index in range(5):
        await emit(agent, f"turn-{index}")

    assert manager._queue.maxsize == 4
    with pytest.raises(transcription.TranscriptionQueueOverflow, match=r"player-two.*limit 4") as overflow:
        await receive(manager)
    assert overflow.value.rejected_count == 1

    manager._record_failure("player-one", ConnectionError("provider stopped"))
    with pytest.raises(RuntimeError, match=r"player-one.*provider stopped"):
        await receive(manager)
    assert [await receive(manager) for _ in range(4)] == [
        AuthenticatedTranscript("player-two", f"turn-{index}", 7) for index in range(4)
    ]
    await manager.aclose()


async def test_repeated_overflow_is_coalesced_and_unconsumed_overflow_fails_close() -> None:
    manager = MultiParticipantTranscriber(Room(), stt=None, authorizer=authorize)
    agent = _TranscriberAgent("player-one", 3, manager._emit_transcript, fail_unexpected, None)

    for index in range(7):
        await emit(agent, f"turn-{index}")

    with pytest.raises(transcription.TranscriptionQueueOverflow, match=r"player-one.*limit 4") as overflow:
        await manager.aclose()
    assert overflow.value.rejected_count == 3


async def test_input_sessions_require_a_full_second_of_silence_to_complete_a_turn() -> None:
    # EndpointingOptions is a total=False TypedDict, so a dropped or misspelled key is
    # accepted in silence and the session keeps the SDK delay — only the resolved value
    # distinguishes the shipped setting from the default.
    resolved = transcription._input_session().options.endpointing
    assert resolved.get("min_delay") == transcription.COMPLETE_UTTERANCE_ENDPOINTING_SECONDS == 1.0
    default_delay = AgentSession(max_tool_steps=5).options.endpointing.get("min_delay")
    assert default_delay is not None and default_delay < 1.0
