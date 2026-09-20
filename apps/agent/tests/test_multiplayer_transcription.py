from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest
from livekit.agents import ErrorEvent, StopResponse, llm, room_io
from livekit.agents import stt as stt_api

from multiplayer_transcription import AuthenticatedTranscript, MultiParticipantTranscriber


@dataclass
class Participant:
    identity: str


class Room:
    def __init__(self, identities: tuple[str, ...] = ()):
        self.remote_participants = {identity: Participant(identity) for identity in identities}
        self.listeners: dict[str, list] = {}

    def on(self, event: str, callback) -> None:
        self.listeners.setdefault(event, []).append(callback)

    def off(self, event: str, callback) -> None:
        self.listeners[event].remove(callback)

    def emit(self, event: str, participant: Participant) -> None:
        for callback in tuple(self.listeners.get(event, ())):
            callback(participant)


class Session:
    def __init__(self):
        self.closed = 0
        self.listeners: dict[str, list] = {}

    def on(self, event: str, callback) -> None:
        self.listeners.setdefault(event, []).append(callback)

    async def aclose(self) -> None:
        self.closed += 1

    def emit_error(self, error: object) -> None:
        for callback in tuple(self.listeners.get("error", ())):
            callback(ErrorEvent(error=error, source=None))


class Factory:
    def __init__(self):
        self.calls: list[tuple[str, Any, room_io.RoomOptions, Session]] = []

    async def __call__(self, identity, agent, options):
        session = Session()
        self.calls.append((identity, agent, options, session))
        return session


async def settle() -> None:
    await asyncio.sleep(0)
    await asyncio.sleep(0)


async def next_item(manager: MultiParticipantTranscriber) -> AuthenticatedTranscript:
    """Bound every consumer wait so a guard that stops surfacing reds instead of hanging."""
    return await asyncio.wait_for(manager.receive(), 1)


def message(text: str) -> llm.ChatMessage:
    return llm.ChatMessage(role="user", content=[text])


def provider_error(recoverable: bool) -> stt_api.STTError:
    return stt_api.STTError(
        timestamp=0.0,
        label="deepgram.STT",
        error=ConnectionError("stream broke"),
        recoverable=recoverable,
    )


async def test_two_existing_participants_get_exact_room_options_and_bound_transcripts() -> None:
    room = Room(("player-one", "player-two"))
    factory = Factory()
    manager = MultiParticipantTranscriber(room, stt=None, session_factory=factory)
    manager.start()
    await settle()

    assert {identity for identity, *_ in factory.calls} == {"player-one", "player-two"}
    assert factory.calls
    agents = {}
    for identity, agent, options, _session in factory.calls:
        agents[identity] = agent
        assert options.participant_identity == identity
        assert options.audio_input is True
        assert options.text_input is False
        assert options.audio_output is False
        assert options.text_output is False
        assert options.close_on_disconnect is False

    with pytest.raises(StopResponse):
        await agents["player-two"].on_user_turn_completed(llm.ChatContext.empty(), message("second phrase"))
    with pytest.raises(StopResponse):
        await agents["player-one"].on_user_turn_completed(llm.ChatContext.empty(), message("first phrase"))
    assert await next_item(manager) == AuthenticatedTranscript("player-two", "second phrase")
    assert await next_item(manager) == AuthenticatedTranscript("player-one", "first phrase")
    await manager.aclose()


async def test_join_duplicate_disconnect_and_reconnect_are_isolated() -> None:
    room = Room(("player-one",))
    factory = Factory()
    manager = MultiParticipantTranscriber(room, stt=None, session_factory=factory)
    manager.start()
    room.emit("participant_connected", Participant("player-two"))
    room.emit("participant_connected", Participant("player-two"))
    await settle()
    room.emit("participant_connected", Participant("player-two"))
    assert len(factory.calls) == 2

    first = {identity: session for identity, _agent, _options, session in factory.calls}
    room.emit("participant_disconnected", Participant("player-two"))
    await settle()
    assert first["player-two"].closed == 1
    assert first["player-one"].closed == 0
    assert manager.active_identities == {"player-one"}

    room.emit("participant_connected", Participant("player-two"))
    await settle()
    assert [identity for identity, *_ in factory.calls].count("player-two") == 2
    await manager.aclose()


async def test_unknown_identity_is_preserved_and_empty_identity_fails() -> None:
    room = Room()
    factory = Factory()
    manager = MultiParticipantTranscriber(room, stt=None, session_factory=factory)
    manager.start()
    room.emit("participant_connected", Participant("unregistered-player"))
    await settle()
    _identity, agent, _options, _session = factory.calls[0]
    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(llm.ChatContext.empty(), message("unknown speaker"))
    assert (await next_item(manager)).participant_identity == "unregistered-player"
    with pytest.raises(ValueError, match="identity is empty"):
        room.emit("participant_connected", Participant(""))
    await manager.aclose()


async def test_empty_completed_transcript_reaches_the_consumer_instead_of_emitting() -> None:
    room = Room(("player-one",))
    factory = Factory()
    manager = MultiParticipantTranscriber(room, stt=None, session_factory=factory)
    manager.start()
    await settle()
    agent = factory.calls[0][1]
    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(llm.ChatContext.empty(), message("   "))
    with pytest.raises(RuntimeError, match=r"player-one.*was empty"):
        await next_item(manager)
    assert manager._queue.empty()
    await manager.aclose()


async def test_listener_precedes_inventory_and_snapshot_join_is_deduplicated() -> None:
    room = Room(("player-one", "player-two"))
    snapshot = room.remote_participants

    class Inventory(dict):
        def values(self):
            room.emit("participant_connected", Participant("player-two"))
            return snapshot.values()

    room.remote_participants = Inventory(snapshot)
    factory = Factory()
    manager = MultiParticipantTranscriber(room, stt=None, session_factory=factory)
    manager.start()
    await settle()
    assert {identity for identity, *_ in factory.calls} == {"player-one", "player-two"}
    assert len(factory.calls) == 2
    await manager.aclose()


async def test_start_and_session_errors_reach_consumer_with_identity_and_cause() -> None:
    room = Room(("bad-start",))

    async def fail_factory(identity, agent, options):
        raise OSError("provider unavailable")

    manager = MultiParticipantTranscriber(room, stt=None, session_factory=fail_factory)
    manager.start()
    with pytest.raises(RuntimeError, match=r"bad-start.*provider unavailable") as caught:
        await next_item(manager)
    assert isinstance(caught.value.__cause__, OSError)
    await manager.aclose()

    room = Room(("bad-stream",))
    factory = Factory()
    manager = MultiParticipantTranscriber(room, stt=None, session_factory=factory)
    manager.start()
    await settle()
    factory.calls[0][3].emit_error(provider_error(recoverable=False))
    with pytest.raises(RuntimeError, match=r"bad-stream.*deepgram\.STT.*stream broke"):
        await next_item(manager)
    factory.calls[0][3].emit_error(ConnectionError("socket closed"))
    with pytest.raises(RuntimeError, match=r"bad-stream.*socket closed") as caught:
        await next_item(manager)
    assert isinstance(caught.value.__cause__, ConnectionError)
    await manager.aclose()


async def test_a_retried_provider_error_does_not_fail_the_stream() -> None:
    room = Room(("player-one",))
    factory = Factory()
    manager = MultiParticipantTranscriber(room, stt=None, session_factory=factory)
    manager.start()
    await settle()
    factory.calls[0][3].emit_error(provider_error(recoverable=True))
    agent = factory.calls[0][1]
    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(llm.ChatContext.empty(), message("still speaking"))
    assert await next_item(manager) == AuthenticatedTranscript("player-one", "still speaking")
    await manager.aclose()


async def test_unconsumed_error_is_raised_by_close() -> None:
    room = Room(("player-one",))

    async def fail_factory(identity, agent, options):
        raise OSError("start broke")

    manager = MultiParticipantTranscriber(room, stt=None, session_factory=fail_factory)
    manager.start()
    await settle()
    with pytest.raises(RuntimeError, match=r"player-one.*start broke"):
        await manager.aclose()


async def test_close_waits_for_each_session() -> None:
    gates = {identity: asyncio.Event() for identity in ("player-one", "player-two")}

    class DelayedSession(Session):
        def __init__(self, identity: str):
            super().__init__()
            self.identity = identity

        async def aclose(self) -> None:
            await gates[self.identity].wait()
            await super().aclose()

    sessions = {}

    async def factory(identity, agent, options):
        sessions[identity] = DelayedSession(identity)
        return sessions[identity]

    manager = MultiParticipantTranscriber(Room(("player-one", "player-two")), stt=None, session_factory=factory)
    manager.start()
    await settle()
    close_task = asyncio.create_task(manager.aclose())
    await settle()
    assert not close_task.done()
    gates["player-one"].set()
    await settle()
    assert not close_task.done()
    gates["player-two"].set()
    await close_task
    assert all(session.closed == 1 for session in sessions.values())
