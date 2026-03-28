"""Tests for prologue narration via agent audio track."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from prologue import play_prologue


def _make_emitter(mock: MagicMock) -> MagicMock:
    """Wire up event emitter methods (_listeners, on, off) on a MagicMock."""
    mock._listeners = {}

    def _on(event, callback):
        mock._listeners.setdefault(event, []).append(callback)

    def _off(event, callback):
        listeners = mock._listeners.get(event, [])
        if callback in listeners:
            listeners.remove(callback)

    mock.on = MagicMock(side_effect=_on)
    mock.off = MagicMock(side_effect=_off)
    return mock


def _mock_room(*, with_participant: bool = True):
    """Create a mock Room, optionally with a remote participant already connected."""
    room = MagicMock()
    if with_participant:
        room.remote_participants = {"player": MagicMock()}
    else:
        room.remote_participants = {}
        _make_emitter(room)
    return room


def _emit(mock, event, **kwargs):
    """Simulate emitting an event on a mock with _listeners."""
    ev = SimpleNamespace(**kwargs)
    for cb in list(mock._listeners.get(event, [])):
        cb(ev)


def _mock_session(*, interrupted: bool = False):
    """Create a mock AgentSession whose say() returns a mock SpeechHandle."""
    session = MagicMock()
    handle = MagicMock()
    handle.interrupted = interrupted
    handle.wait_for_playout = AsyncMock()
    session.say = MagicMock(return_value=handle)
    return session, handle


class TestPlayPrologue:
    async def test_plays_audio_through_agent_track(self):
        session, handle = _mock_session()
        room = _mock_room()

        with (
            patch("prologue.os.path.isfile", return_value=True),
            patch("prologue.audio_frames_from_file") as mock_frames,
        ):
            mock_frames.return_value = AsyncMock()
            await play_prologue(session, room)

        session.say.assert_called_once()
        call_kwargs = session.say.call_args
        assert call_kwargs.kwargs["allow_interruptions"] is True
        assert call_kwargs.kwargs["add_to_chat_ctx"] is False
        handle.wait_for_playout.assert_awaited_once()

    async def test_returns_false_when_not_interrupted(self):
        session, _handle = _mock_session(interrupted=False)
        room = _mock_room()

        with patch("prologue.os.path.isfile", return_value=True), patch("prologue.audio_frames_from_file"):
            result = await play_prologue(session, room)

        assert result is False

    async def test_returns_true_when_interrupted(self):
        session, _handle = _mock_session(interrupted=True)
        room = _mock_room()

        with patch("prologue.os.path.isfile", return_value=True), patch("prologue.audio_frames_from_file"):
            result = await play_prologue(session, room)

        assert result is True

    async def test_skips_when_file_missing(self):
        session, _handle = _mock_session()
        room = _mock_room()

        with patch("prologue.os.path.isfile", return_value=False):
            result = await play_prologue(session, room)

        assert result is False
        session.say.assert_not_called()

    async def test_waits_for_participant_before_playing(self):
        session, _handle = _mock_session()
        room = _mock_room(with_participant=False)

        with patch("prologue.os.path.isfile", return_value=True), patch("prologue.audio_frames_from_file"):

            async def _join_soon():
                await asyncio.sleep(0.02)
                _emit(room, "participant_connected")

            join_task = asyncio.create_task(_join_soon())
            await play_prologue(session, room)
            await join_task

        session.say.assert_called_once()
