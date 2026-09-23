"""Tests for primary-player reconnect grace and background pause/resume."""

import asyncio
import logging
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


class ClosingSession:
    def __init__(self):
        self.handlers = {}
        self.close_count = 0
        self.generate_reply = MagicMock()

    def on(self, event, callback):
        self.handlers[event] = callback

    def off(self, event, callback):
        assert self.handlers[event] == callback
        del self.handlers[event]

    async def aclose(self):
        self.close_count += 1
        self.handlers["close"](SimpleNamespace())
        await asyncio.sleep(0)


async def test_session_close_owns_and_joins_reconnect_cleanup():
    from participant_lifecycle import RECONNECT_GRACE_S, _setup_reconnection

    room = Room()
    session = ClosingSession()
    clock = ManualSleep()
    userdata = SessionData(player_id="player-one", location_id="loc")
    owner = _setup_reconnection(cast(Any, room), cast(Any, session), userdata, MagicMock(), sleep=clock)

    assert "close" in session.handlers
    room.emit("participant_disconnected", "player-one")
    await asyncio.sleep(0)
    await session.aclose()
    assert owner.close_task is not None
    await asyncio.wait_for(owner.close_task, 1)
    assert room.handlers == {}
    assert session.handlers == {}
    await clock.advance(RECONNECT_GRACE_S)
    assert session.close_count == 1


async def test_grace_expiry_closes_without_canceling_its_own_session_close():
    from participant_lifecycle import RECONNECT_GRACE_S, _setup_reconnection

    room = Room()
    session = ClosingSession()
    clock = ManualSleep()
    userdata = SessionData(player_id="player-one", location_id="loc")
    owner = _setup_reconnection(cast(Any, room), cast(Any, session), userdata, MagicMock(), sleep=clock)

    room.emit("participant_disconnected", "player-one")
    await asyncio.sleep(0)
    await clock.advance(RECONNECT_GRACE_S)
    async with asyncio.timeout(1):
        while owner.close_task is None:
            await asyncio.sleep(0)
    await asyncio.wait_for(owner.close_task, 1)
    await asyncio.wait_for(owner._deadlines["player-one"], 1)
    assert session.close_count == 1
    assert room.handlers == {}


async def test_a_failed_reconnect_task_is_reported_rather_than_left_unretrieved(caplog) -> None:
    """Nothing awaits close_task in production, so the cleanup failure has to reach the log here."""
    from participant_lifecycle import _setup_reconnection

    caplog.set_level(logging.ERROR, logger="divineruin.dm")
    room = Room()
    session = ClosingSession()
    session.generate_reply = MagicMock(side_effect=OSError("reconnect greeting failed"))
    userdata = SessionData(player_id="player-one", location_id="loc")
    owner = _setup_reconnection(cast(Any, room), cast(Any, session), userdata, MagicMock(), sleep=ManualSleep())

    room.emit("participant_disconnected", "player-one")
    await asyncio.sleep(0)
    room.emit("participant_connected", "player-one")
    async with asyncio.timeout(1):
        while not all(task.done() for task in owner._tasks):
            await asyncio.sleep(0)

    await session.aclose()
    assert owner.close_task is not None
    async with asyncio.timeout(1):
        while not owner.close_task.done():
            await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert owner.close_task.exception() is not None
    assert [record.message for record in caplog.records] == ["Reconnect cleanup failed for 'player-one'"]


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

        session = SimpleNamespace(
            aclose=AsyncMock(), generate_reply=MagicMock(return_value=object()), on=MagicMock(), off=MagicMock()
        )
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
    session = SimpleNamespace(aclose=AsyncMock(), on=MagicMock(), off=MagicMock())
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
    session = SimpleNamespace(
        aclose=AsyncMock(), generate_reply=MagicMock(return_value=object()), on=MagicMock(), off=MagicMock()
    )
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


async def test_a_repeat_disconnect_neither_re_pauses_nor_rearms_the_grace():
    from participant_lifecycle import RECONNECT_GRACE_S, _setup_reconnection

    room = Room()
    clock = ManualSleep()
    session = SimpleNamespace(
        aclose=AsyncMock(), generate_reply=MagicMock(return_value=object()), on=MagicMock(), off=MagicMock()
    )
    userdata = SessionData(player_id="player-one", location_id="loc")
    userdata.background = MagicMock()
    owner = _setup_reconnection(cast(Any, room), cast(Any, session), userdata, MagicMock(), sleep=clock)

    room.emit("participant_disconnected", "player-one")
    room.emit("participant_disconnected", "player-one")
    await asyncio.sleep(0)

    userdata.background.pause.assert_called_once()
    assert len(clock.waiters) == 1
    await clock.advance(RECONNECT_GRACE_S)
    session.aclose.assert_awaited_once()
    await owner.aclose()


async def test_a_drop_while_the_reconnect_is_settling_keeps_the_new_grace_and_never_resumes():
    """The reconnect handler defers to a task, so the player can drop again before it runs; the
    resume/re-greet it would have done belongs to a connection that is already gone."""
    from participant_lifecycle import RECONNECT_GRACE_S, _setup_reconnection

    room = Room()
    clock = ManualSleep()
    session = SimpleNamespace(
        aclose=AsyncMock(), generate_reply=MagicMock(return_value=object()), on=MagicMock(), off=MagicMock()
    )
    agent = SimpleNamespace(_fire_and_forget=MagicMock())
    userdata = SessionData(player_id="player-one", location_id="loc")
    userdata.background = MagicMock()
    owner = _setup_reconnection(cast(Any, room), cast(Any, session), userdata, cast(Any, agent), sleep=clock)

    room.emit("participant_disconnected", "player-one")
    await asyncio.sleep(0)
    armed = set(owner._tasks)
    room.emit("participant_connected", "player-one")
    settling = (set(owner._tasks) - armed).pop()
    room.emit("participant_disconnected", "player-one")
    await asyncio.wait_for(settling, 1)

    userdata.background.resume.assert_not_called()
    session.generate_reply.assert_not_called()
    await clock.advance(RECONNECT_GRACE_S)
    session.aclose.assert_awaited_once()
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
