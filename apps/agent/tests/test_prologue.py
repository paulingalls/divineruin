"""Tests for interruptible prologue narration."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import event_types as E
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


def _mock_session():
    """Create a mock AgentSession with on/off event methods."""
    return _make_emitter(MagicMock())


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


class TestPlayPrologue:
    async def test_completes_after_duration(self):
        session = _mock_session()
        room = _mock_room()

        with patch("prologue.publish_game_event", new_callable=AsyncMock) as mock_pub:
            with patch("prologue.PROLOGUE_DURATION_S", 0.05):
                interrupted = await play_prologue(session, room)

        assert interrupted is False
        calls = [c.args[1] for c in mock_pub.await_args_list]
        assert E.PLAY_NARRATION in calls
        assert E.STOP_NARRATION not in calls

    async def test_interrupts_on_player_speech(self):
        session = _mock_session()
        room = _mock_room()

        with patch("prologue.publish_game_event", new_callable=AsyncMock) as mock_pub:
            with patch("prologue.PROLOGUE_DURATION_S", 10):

                async def _speak_soon():
                    await asyncio.sleep(0.02)
                    _emit(session, "user_state_changed", new_state="speaking")

                speak_task = asyncio.create_task(_speak_soon())
                interrupted = await play_prologue(session, room)
                await speak_task

        assert interrupted is True
        calls = [c.args[1] for c in mock_pub.await_args_list]
        assert E.PLAY_NARRATION in calls
        assert E.STOP_NARRATION in calls

    async def test_cleans_up_listener_on_completion(self):
        session = _mock_session()
        room = _mock_room()

        with patch("prologue.publish_game_event", new_callable=AsyncMock):
            with patch("prologue.PROLOGUE_DURATION_S", 0.02):
                await play_prologue(session, room)

        session.on.assert_called_once_with("user_state_changed", session.on.call_args[0][1])
        session.off.assert_called_once_with("user_state_changed", session.on.call_args[0][1])
        assert len(session._listeners.get("user_state_changed", [])) == 0

    async def test_cleans_up_listener_on_interruption(self):
        session = _mock_session()
        room = _mock_room()

        with patch("prologue.publish_game_event", new_callable=AsyncMock):
            with patch("prologue.PROLOGUE_DURATION_S", 10):

                async def _speak_soon():
                    await asyncio.sleep(0.02)
                    _emit(session, "user_state_changed", new_state="speaking")

                speak_task = asyncio.create_task(_speak_soon())
                await play_prologue(session, room)
                await speak_task

        session.off.assert_called_once()
        assert len(session._listeners.get("user_state_changed", [])) == 0

    async def test_waits_for_participant_before_publishing(self):
        session = _mock_session()
        room = _mock_room(with_participant=False)

        with patch("prologue.publish_game_event", new_callable=AsyncMock) as mock_pub:
            with patch("prologue.PROLOGUE_DURATION_S", 0.05):

                async def _join_soon():
                    await asyncio.sleep(0.02)
                    _emit(room, "participant_connected")

                join_task = asyncio.create_task(_join_soon())
                interrupted = await play_prologue(session, room)
                await join_task

        assert interrupted is False
        calls = [c.args[1] for c in mock_pub.await_args_list]
        assert E.PLAY_NARRATION in calls

    async def test_ignores_non_speaking_state(self):
        session = _mock_session()
        room = _mock_room()

        with patch("prologue.publish_game_event", new_callable=AsyncMock) as mock_pub:
            with patch("prologue.PROLOGUE_DURATION_S", 0.05):

                async def _emit_listening():
                    await asyncio.sleep(0.01)
                    _emit(session, "user_state_changed", new_state="listening")

                task = asyncio.create_task(_emit_listening())
                interrupted = await play_prologue(session, room)
                await task

        assert interrupted is False
        calls = [c.args[1] for c in mock_pub.await_args_list]
        assert E.STOP_NARRATION not in calls
