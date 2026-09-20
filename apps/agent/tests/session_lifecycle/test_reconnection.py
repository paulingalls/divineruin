"""Tests for primary-player reconnect grace and background pause/resume."""

import asyncio
import time
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

from session_data import SessionData


class Room:
    def __init__(self):
        self.handlers = {}

    def on(self, event, callback=None):
        if callback is not None:
            self.handlers[event] = callback
            return callback

        def register(fn):
            self.handlers[event] = fn
            return fn

        return register

    def emit(self, event, identity):
        self.handlers[event](SimpleNamespace(identity=identity))

    def off(self, event, callback):
        assert self.handlers[event] == callback
        del self.handlers[event]


class ManualSleep:
    def __init__(self):
        self.now = 0
        self.waiters = []

    async def __call__(self, delay):
        future = asyncio.get_running_loop().create_future()
        self.waiters.append((self.now + delay, future))
        await future

    async def advance(self, seconds):
        self.now += seconds
        for deadline, future in tuple(self.waiters):
            if deadline <= self.now and not future.done():
                future.set_result(None)
        await asyncio.sleep(0)
        await asyncio.sleep(0)


class TestReconnectionSetup:
    """Test _setup_reconnection registers handlers for any agent type."""

    def test_setup_reconnection_registers_handlers(self):
        from participant_lifecycle import _setup_reconnection

        room = MagicMock()
        session = MagicMock()
        userdata = SessionData(player_id="p1", location_id="loc1")

        _setup_reconnection(room, session, userdata, MagicMock())

        # Should register both participant_disconnected and participant_connected
        on_calls = [call.args[0] for call in room.on.call_args_list]
        assert "participant_disconnected" in on_calls
        assert "participant_connected" in on_calls

    def test_setup_reconnection_works_without_background(self):
        """Creation/onboarding sessions have no background process yet."""
        from participant_lifecycle import _setup_reconnection

        room = MagicMock()
        session = MagicMock()
        userdata = SessionData(player_id="p1", location_id="loc1")
        assert userdata.background is None

        # Should not raise
        _setup_reconnection(room, session, userdata, MagicMock())

    async def test_drop_pauses_and_reconnect_resumes_the_sessions_process(self):
        """The process hangs off the SESSION, so the handlers must reach it there — reading it
        off the agent they were wired with would silently stop pausing after the first handoff."""
        from participant_lifecycle import _setup_reconnection

        room = Room()
        userdata = SessionData(player_id="p1", location_id="loc1")
        background = MagicMock()
        userdata.background = background
        participant = MagicMock()
        participant.identity = "p1"

        session = SimpleNamespace(aclose=AsyncMock(), generate_reply=MagicMock(return_value=object()))
        agent = SimpleNamespace(_fire_and_forget=MagicMock())
        owner = _setup_reconnection(cast(Any, room), cast(Any, session), userdata, cast(Any, agent))

        room.handlers["participant_disconnected"](participant)
        background.pause.assert_called_once()
        await asyncio.sleep(0)

        # The reconnect cancels the grace timeout the drop armed, so no task outlives the test.
        room.handlers["participant_connected"](participant)
        async with asyncio.timeout(1):
            while not background.resume.called:
                await asyncio.sleep(0)
        background.resume.assert_called_once()
        await owner.aclose()


async def test_primary_closes_at_grace_expiry_while_secondary_disconnect_is_ignored():
    from participant_lifecycle import RECONNECT_GRACE_S, _setup_reconnection

    room = Room()
    clock = ManualSleep()
    session = SimpleNamespace(aclose=AsyncMock())
    userdata = SessionData(player_id="player-one", location_id="loc")
    owner = _setup_reconnection(cast(Any, room), cast(Any, session), userdata, MagicMock(), sleep=clock)

    room.emit("participant_disconnected", "player-two")
    await clock.advance(RECONNECT_GRACE_S)
    session.aclose.assert_not_awaited()

    room.emit("participant_disconnected", "player-one")
    await asyncio.sleep(0)
    await clock.advance(RECONNECT_GRACE_S - 1)
    session.aclose.assert_not_awaited()
    await clock.advance(1)
    session.aclose.assert_awaited_once()
    await owner.aclose()


async def test_reconnect_cancels_old_deadline_and_resumes_once():
    from participant_lifecycle import RECONNECT_GRACE_S, _setup_reconnection

    room = Room()
    clock = ManualSleep()
    session = SimpleNamespace(aclose=AsyncMock(), generate_reply=MagicMock(return_value=object()))
    agent = SimpleNamespace(_fire_and_forget=MagicMock())
    userdata = SessionData(player_id="player-one", location_id="loc")
    userdata.background = MagicMock()
    owner = _setup_reconnection(
        cast(Any, room),
        cast(Any, session),
        userdata,
        cast(Any, agent),
        sleep=clock,
    )

    room.emit("participant_disconnected", "player-one")
    await asyncio.sleep(0)
    room.emit("participant_connected", "player-one")
    room.emit("participant_connected", "player-one")
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    await clock.advance(RECONNECT_GRACE_S)

    session.aclose.assert_not_awaited()
    userdata.background.pause.assert_called_once()
    userdata.background.resume.assert_called_once()
    session.generate_reply.assert_called_once()
    await owner.aclose()


class TestBackgroundProcessPauseResume:
    """Test pause/resume on BackgroundProcess."""

    def test_pause_sets_flag(self):
        from background_process import BackgroundProcess

        bp = BackgroundProcess(session=MagicMock(), session_data=MagicMock())
        assert bp._paused is False
        bp.pause()
        assert bp._paused is True

    def test_resume_clears_flag(self):
        from background_process import BackgroundProcess

        bp = BackgroundProcess(session=MagicMock(), session_data=MagicMock())
        bp.pause()
        bp.resume()
        assert bp._paused is False


class TestDisconnectFlags:
    """Test disconnect/reconnect flags on SessionData."""

    def test_disconnect_sets_flags(self):
        sd = SessionData(player_id="p1", location_id="loc1")
        sd.player_disconnected = True
        sd.disconnect_time = time.time()
        assert sd.player_disconnected is True
        assert sd.disconnect_time > 0

    def test_reconnect_clears_flag(self):
        sd = SessionData(player_id="p1", location_id="loc1")
        sd.player_disconnected = True
        sd.player_disconnected = False
        assert sd.player_disconnected is False
