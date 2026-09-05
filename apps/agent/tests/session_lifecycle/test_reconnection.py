"""Tests for reconnection setup, background pause/resume, and disconnect flags."""

import time
from unittest.mock import MagicMock

from session_data import SessionData


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

        handlers = {}

        def _register(event):
            def _decorate(fn):
                handlers[event] = fn
                return fn

            return _decorate

        room = MagicMock()
        room.on = _register
        userdata = SessionData(player_id="p1", location_id="loc1")
        background = MagicMock()
        userdata.background = background
        participant = MagicMock()
        participant.identity = "p1"

        _setup_reconnection(room, MagicMock(), userdata, MagicMock())

        handlers["participant_disconnected"](participant)
        background.pause.assert_called_once()

        # The reconnect cancels the grace timeout the drop armed, so no task outlives the test.
        handlers["participant_connected"](participant)
        background.resume.assert_called_once()


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
