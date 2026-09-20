from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, cast

import pytest
from livekit.agents import Agent, room_io

from multiplayer_transcription import MultiParticipantTranscriber


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
        # rtc.EventEmitter.off discards a callback it never registered rather than raising.
        listeners = self.listeners.get(event, [])
        if callback in listeners:
            listeners.remove(callback)

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


class Factory:
    def __init__(self):
        self.calls: list[tuple[str, Any, room_io.RoomOptions, Session]] = []

    async def __call__(self, identity: str, agent: Agent, options: room_io.RoomOptions) -> Any:
        session = Session()
        self.calls.append((identity, agent, options, session))
        return session


async def settle() -> None:
    await asyncio.sleep(0)
    await asyncio.sleep(0)


async def authorize_all(_identity: str) -> int:
    return 1


async def test_unconsumed_error_is_raised_by_close() -> None:
    room = Room(("player-one",))

    async def fail_factory(identity, agent, options):
        raise OSError("start broke")

    manager = MultiParticipantTranscriber(room, stt=None, authorizer=authorize_all, session_factory=fail_factory)
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

    manager = MultiParticipantTranscriber(
        Room(("player-one", "player-two")),
        stt=None,
        authorizer=authorize_all,
        session_factory=cast(Any, factory),
    )
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


async def test_close_cancels_and_joins_a_starter() -> None:
    started = asyncio.Event()
    hold_authorization = asyncio.Event()

    async def authorize(_identity):
        started.set()
        await hold_authorization.wait()
        return 1

    room = Room(("player-one",))
    manager = MultiParticipantTranscriber(room, stt=None, authorizer=authorize, session_factory=Factory())
    manager.start()
    await started.wait()
    starter = manager._starting["player-one"]

    await asyncio.wait_for(manager.aclose(), 1)

    assert starter.cancelled()
    assert manager.active_identities == frozenset()
    assert room.listeners["participant_connected"] == []
    assert room.listeners["participant_disconnected"] == []


async def test_events_and_repeated_close_after_shutdown_do_nothing() -> None:
    room = Room(("player-one",))
    factory = Factory()
    manager = MultiParticipantTranscriber(room, stt=None, authorizer=authorize_all, session_factory=factory)
    manager.start()
    await settle()

    await manager.aclose()
    await manager.aclose()
    room.emit("participant_connected", Participant("player-two"))
    await settle()

    assert [identity for identity, *_ in factory.calls] == ["player-one"]
    assert factory.calls[0][3].closed == 1


async def test_close_preserves_both_session_failures() -> None:
    errors = {identity: OSError(f"{identity} close failed") for identity in ("player-one", "player-two")}

    class FailingSession(Session):
        def __init__(self, identity):
            super().__init__()
            self.identity = identity

        async def aclose(self) -> None:
            raise errors[self.identity]

    async def factory(identity, _agent, _options):
        return FailingSession(identity)

    manager = MultiParticipantTranscriber(
        Room(("player-one", "player-two")),
        stt=None,
        authorizer=authorize_all,
        session_factory=cast(Any, factory),
    )
    manager.start()
    await settle()

    with pytest.raises(BaseExceptionGroup) as caught:
        await manager.aclose()

    assert {failure.__cause__ for failure in caught.value.exceptions} == set(errors.values())


async def test_start_after_close_refuses_loudly() -> None:
    manager = MultiParticipantTranscriber(
        Room(("player-one",)), stt=None, authorizer=authorize_all, session_factory=Factory()
    )
    await manager.aclose()

    with pytest.raises(RuntimeError, match="closed"):
        manager.start()
