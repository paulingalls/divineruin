from __future__ import annotations

import asyncio
import functools
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from livekit.agents import Agent, AgentSession, StopResponse, llm, room_io, stt


@dataclass(frozen=True)
class AuthenticatedTranscript:
    participant_identity: str
    text: str
    generation: int
    speech_events: tuple[stt.SpeechEvent, ...] = ()


class TranscriptionFailure(RuntimeError):
    pass


MAX_PENDING_TRANSCRIPTS = 4
COMPLETE_UTTERANCE_ENDPOINTING_SECONDS = 1.0


class TranscriptionQueueOverflow(TranscriptionFailure):
    def __init__(self, participant_identity: str, limit: int):
        self.participant_identities = {participant_identity}
        self.limit = limit
        self.rejected_count = 1

    def add_rejection(self, participant_identity: str) -> None:
        self.participant_identities.add(participant_identity)
        self.rejected_count += 1

    def __str__(self) -> str:
        identities = ", ".join(repr(identity) for identity in sorted(self.participant_identities))
        return (
            f"transcription queue overflow for {identities}: pending limit {self.limit}; "
            f"rejected {self.rejected_count} turn(s)"
        )


class _TranscriberAgent(Agent):
    def __init__(
        self,
        identity: str,
        generation: int,
        emit: Callable[[AuthenticatedTranscript], None],
        fail: Callable[[BaseException], None],
        stt: Any,
    ):
        super().__init__(instructions="Transcribe the linked participant.", stt=stt)
        self.identity = identity
        self.generation = generation
        self._emit = emit
        self._fail = fail
        self._final_events: deque[stt.SpeechEvent] = deque()

    async def stt_node(self, audio, model_settings):
        async for event in Agent.default.stt_node(self, audio, model_settings):
            if event.type == stt.SpeechEventType.FINAL_TRANSCRIPT and event.alternatives:
                self._final_events.append(event)
            yield event

    async def on_user_turn_completed(self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage) -> None:
        text = (new_message.text_content or "").strip()
        if not text:
            # AgentActivity logs and discards anything raised out of this hook, so raising here
            # would leave the consumer with a healthy-looking silent stream.
            self._fail(ValueError(f"completed transcript for {self.identity!r} was empty"))
        else:
            events = tuple(self._final_events)
            self._final_events.clear()
            self._emit(AuthenticatedTranscript(self.identity, text, self.generation, events))
        raise StopResponse()


SessionFactory = Callable[[str, Agent, room_io.RoomOptions], Awaitable[AgentSession]]
Authorizer = Callable[[str], Awaitable[int | None]]


def _input_session() -> AgentSession:
    """Build the input-only session for one authorized player track.

    No llm, so no tool chain — but every AgentSession site in this repo states its
    ceiling rather than inheriting the plugin default (test_strict_tool_budget).
    Endpointing overrides the SDK default because each committed turn is delivered
    to the DM on its own: a mid-sentence pause that ends the turn early does not
    merely delay the rest, it splits one utterance into two authenticated turns.
    """
    return AgentSession(
        max_tool_steps=5,
        turn_handling={"endpointing": {"min_delay": COMPLETE_UTTERANCE_ENDPOINTING_SECONDS}},
    )


class MultiParticipantTranscriber:
    def __init__(
        self,
        room: Any,
        *,
        stt: Any,
        authorizer: Authorizer,
        session_factory: SessionFactory | None = None,
    ):
        self.room = room
        self.stt = stt
        self._authorizer = authorizer
        self._session_factory = session_factory
        self._queue: asyncio.Queue[AuthenticatedTranscript | BaseException] = asyncio.Queue(
            maxsize=MAX_PENDING_TRANSCRIPTS
        )
        self._pending_failures: deque[BaseException] = deque()
        self._pending_overflow: TranscriptionQueueOverflow | None = None
        self._active: dict[str, AgentSession] = {}
        self._starting: dict[str, asyncio.Task[None]] = {}
        self._closing: set[asyncio.Task[None]] = set()
        self._failures: list[BaseException] = []
        self._consumed_failures: set[int] = set()
        self._start_counts: dict[str, int] = {}
        self._started = False
        self._closed = False

    @property
    def active_identities(self) -> frozenset[str]:
        return frozenset(self._active)

    @property
    def start_counts(self) -> dict[str, int]:
        return dict(self._start_counts)

    def start(self) -> None:
        if self._closed:
            raise RuntimeError("transcriber is closed")
        if self._started:
            return
        self._started = True
        self.room.on("participant_connected", self._on_connected)
        self.room.on("participant_disconnected", self._on_disconnected)
        participants = list(self.room.remote_participants.values())
        for participant in participants:
            self._on_connected(participant)

    def _on_connected(self, participant: Any) -> None:
        identity = participant.identity
        if identity in self._starting or identity in self._active:
            return
        task = asyncio.create_task(self._start_one(identity))
        self._starting[identity] = task

    def _on_disconnected(self, participant: Any) -> None:
        identity = participant.identity
        starting = self._starting.pop(identity, None)
        if starting is not None:
            starting.cancel()
        session = self._active.pop(identity, None)
        if session is not None:
            self._schedule_close(identity, session)

    def _record_failure(self, identity: str, cause: BaseException) -> None:
        failure = TranscriptionFailure(f"transcription failed for {identity!r}: {cause}")
        failure.__cause__ = cause
        self._failures.append(failure)
        try:
            self._queue.put_nowait(failure)
        except asyncio.QueueFull:
            self._pending_failures.append(failure)

    def _emit_transcript(self, transcript: AuthenticatedTranscript) -> None:
        try:
            self._queue.put_nowait(transcript)
        except asyncio.QueueFull:
            overflow = self._pending_overflow
            if overflow is None:
                overflow = TranscriptionQueueOverflow(transcript.participant_identity, self._queue.maxsize)
                self._pending_overflow = overflow
                self._pending_failures.append(overflow)
                self._failures.append(overflow)
            else:
                overflow.add_rejection(transcript.participant_identity)

    def _schedule_close(self, identity: str, session: AgentSession) -> None:
        async def close() -> None:
            try:
                await session.aclose()
            except Exception as exc:
                self._record_failure(identity, exc)

        task = asyncio.create_task(close())
        self._closing.add(task)
        task.add_done_callback(self._closing.discard)

    async def _start_one(self, identity: str) -> None:
        session: AgentSession | None = None
        try:
            generation = await self._authorizer(identity)
            if generation is None:
                return
            options = room_io.RoomOptions(
                participant_identity=identity,
                audio_input=True,
                text_input=False,
                audio_output=False,
                text_output=False,
                close_on_disconnect=False,
            )
            agent = _TranscriberAgent(
                identity,
                generation,
                self._emit_transcript,
                functools.partial(self._record_failure, identity),
                self.stt,
            )
            if self._session_factory is None:
                session = _input_session()
                await session.start(agent, room=self.room, room_options=options, session_host=False)
            else:
                session = await self._session_factory(identity, agent, options)

            def on_error(event: Any) -> None:
                error = event.error
                # A recoverable provider error is one the SDK is already retrying (STTError /
                # TTSError / LLMError carry the flag); it emits a non-recoverable one when the
                # retries run out, so the stream still fails loud when it is really dead.
                if getattr(error, "recoverable", False):
                    return
                cause = error if isinstance(error, BaseException) else RuntimeError(str(error))
                self._record_failure(identity, cause)

            session.on("error", on_error)
            if self._starting.get(identity) is asyncio.current_task():
                self._active[identity] = session
                self._start_counts[identity] = self._start_counts.get(identity, 0) + 1
            else:
                self._schedule_close(identity, session)
        except asyncio.CancelledError:
            if session is not None:
                self._schedule_close(identity, session)
            raise
        except Exception as exc:
            if session is not None:
                self._schedule_close(identity, session)
            self._record_failure(identity, exc)
        finally:
            if self._starting.get(identity) is asyncio.current_task():
                self._starting.pop(identity, None)

    async def receive(self) -> AuthenticatedTranscript:
        item = self._pending_failures.popleft() if self._pending_failures else await self._queue.get()
        if isinstance(item, BaseException):
            if item is self._pending_overflow:
                self._pending_overflow = None
            self._consumed_failures.add(id(item))
            raise item
        return item

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        # rtc.EventEmitter.off discards a callback it never registered, so an unstarted
        # transcriber needs no gate here.
        self.room.off("participant_connected", self._on_connected)
        self.room.off("participant_disconnected", self._on_disconnected)
        starting = tuple(self._starting.values())
        for task in starting:
            if not task.done():
                task.cancel()
        await asyncio.gather(*starting, return_exceptions=True)
        for identity, session in tuple(self._active.items()):
            self._schedule_close(identity, session)
        closing = tuple(self._closing)
        await asyncio.gather(*closing, return_exceptions=True)
        self._starting.clear()
        self._active.clear()
        unconsumed = [failure for failure in self._failures if id(failure) not in self._consumed_failures]
        self._consumed_failures.update(map(id, unconsumed))
        if len(unconsumed) == 1:
            raise unconsumed[0]
        if unconsumed:
            raise BaseExceptionGroup("transcription cleanup failed", unconsumed)
