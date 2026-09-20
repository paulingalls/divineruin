"""Ownership races while a participant transcription session starts."""

import asyncio
from dataclasses import dataclass

from multiplayer_transcription import MultiParticipantTranscriber


@dataclass
class Participant:
    identity: str


class Room:
    def __init__(self):
        self.remote_participants = {}
        self.listeners: dict[str, list] = {}

    def on(self, event, callback):
        self.listeners.setdefault(event, []).append(callback)

    def off(self, event, callback):
        self.listeners[event].remove(callback)

    def emit(self, event, participant):
        for callback in tuple(self.listeners.get(event, ())):
            callback(participant)


class Session:
    def __init__(self):
        self.closed = 0

    def on(self, _event, _callback):
        pass

    async def aclose(self):
        self.closed += 1


async def _settle():
    await asyncio.sleep(0)
    await asyncio.sleep(0)


async def test_superseded_start_cannot_replace_or_remove_the_reconnected_session() -> None:
    room = Room()
    first_cancelled = asyncio.Event()
    release_first = asyncio.Event()
    release_second = asyncio.Event()
    sessions: list[Session] = []

    async def racing_factory(_identity, _agent, _options):
        session = Session()
        sessions.append(session)
        gate = release_first if len(sessions) == 1 else release_second
        try:
            await gate.wait()
        except asyncio.CancelledError:
            first_cancelled.set()
            await gate.wait()
        return session

    async def authorize(_identity):
        return 1

    manager = MultiParticipantTranscriber(room, stt=None, authorizer=authorize, session_factory=racing_factory)
    manager.start()
    room.emit("participant_connected", Participant("player-one"))
    await _settle()
    room.emit("participant_disconnected", Participant("player-one"))
    await first_cancelled.wait()
    room.emit("participant_connected", Participant("player-one"))
    await _settle()
    try:
        release_first.set()
        await _settle()
        assert "player-one" in manager._starting
        assert manager.active_identities == frozenset()
        assert sessions[0].closed == 1

        release_second.set()
        await _settle()
        assert manager.active_identities == {"player-one"}
        assert manager.start_counts == {"player-one": 1}
        assert sessions[1].closed == 0
    finally:
        release_first.set()
        release_second.set()
        await _settle()
        await manager.aclose()
