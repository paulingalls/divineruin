from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from livekit.agents import Agent, AgentSession, StopResponse, llm, room_io


@dataclass(frozen=True)
class AuthenticatedTranscript:
    participant_identity: str
    text: str


class TranscriptionFailure(RuntimeError):
    pass


class _TranscriberAgent(Agent):
    def __init__(self, identity: str, emit: Callable[[AuthenticatedTranscript], None], stt: Any):
        super().__init__(instructions="Transcribe the linked participant.", stt=stt)
        self.identity = identity
        self._emit = emit

    async def on_user_turn_completed(self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage) -> None:
        text = (new_message.text_content or "").strip()
        if not text:
            raise ValueError(f"completed transcript for {self.identity!r} was empty")
        self._emit(AuthenticatedTranscript(self.identity, text))
        raise StopResponse()


SessionFactory = Callable[[str, Agent, room_io.RoomOptions], Awaitable[AgentSession]]


class MultiParticipantTranscriber:
    def __init__(self, room: Any, *, stt: Any, session_factory: SessionFactory | None = None):
        self.room = room
        self.stt = stt
        self._session_factory = session_factory
        self._queue: asyncio.Queue[AuthenticatedTranscript | BaseException] = asyncio.Queue()
        self._active: dict[str, AgentSession] = {}
        self._starting: dict[str, asyncio.Task[None]] = {}
        self._closing: set[asyncio.Task[None]] = set()
        self._failures: list[BaseException] = []
        self._consumed_failures: set[int] = set()
        self._start_counts: dict[str, int] = {}

    @property
    def active_identities(self) -> frozenset[str]:
        return frozenset(self._active)

    @property
    def start_counts(self) -> dict[str, int]:
        return dict(self._start_counts)

    def start(self) -> None:
        self.room.on("participant_connected", self._on_connected)
        self.room.on("participant_disconnected", self._on_disconnected)
        participants = list(self.room.remote_participants.values())
        for participant in participants:
            self._on_connected(participant)

    def _on_connected(self, participant: Any) -> None:
        identity = participant.identity
        if not identity:
            raise ValueError("LiveKit participant identity is empty")
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
        self._queue.put_nowait(failure)

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
            options = room_io.RoomOptions(
                participant_identity=identity,
                audio_input=True,
                text_input=False,
                audio_output=False,
                text_output=False,
                close_on_disconnect=True,
            )
            agent = _TranscriberAgent(identity, self._queue.put_nowait, self.stt)
            if self._session_factory is None:
                session = AgentSession()
                await session.start(agent, room=self.room, room_options=options, session_host=False)
            else:
                session = await self._session_factory(identity, agent, options)

            def on_error(event: Any) -> None:
                error = event.error
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
        item = await self._queue.get()
        if isinstance(item, BaseException):
            self._consumed_failures.add(id(item))
            raise item
        return item

    async def aclose(self) -> None:
        self.room.off("participant_connected", self._on_connected)
        self.room.off("participant_disconnected", self._on_disconnected)
        starting = tuple(self._starting.values())
        await asyncio.gather(*starting, return_exceptions=True)
        for identity, session in tuple(self._active.items()):
            self._schedule_close(identity, session)
        closing = tuple(self._closing)
        await asyncio.gather(*closing, return_exceptions=True)
        self._starting.clear()
        self._active.clear()
        unconsumed = next((failure for failure in self._failures if id(failure) not in self._consumed_failures), None)
        if unconsumed is not None:
            raise unconsumed
