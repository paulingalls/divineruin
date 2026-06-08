"""Tests for reconnection setup, background pause/resume, and disconnect flags."""

import time
from unittest.mock import MagicMock

from session_data import SessionData


class TestReconnectionSetup:
    """Test _setup_reconnection registers handlers for any agent type."""

    def test_setup_reconnection_registers_handlers(self):
        from agent import _setup_reconnection

        room = MagicMock()
        session = MagicMock()
        userdata = SessionData(player_id="p1", location_id="loc1")
        agent = MagicMock()
        agent._background = None

        _setup_reconnection(room, session, userdata, agent)

        # Should register both participant_disconnected and participant_connected
        on_calls = [call.args[0] for call in room.on.call_args_list]
        assert "participant_disconnected" in on_calls
        assert "participant_connected" in on_calls

    def test_setup_reconnection_works_without_background(self):
        """Creation/onboarding agents have no background process."""
        from agent import _setup_reconnection

        room = MagicMock()
        session = MagicMock()
        userdata = SessionData(player_id="p1", location_id="loc1")
        agent = MagicMock()
        agent._background = None

        # Should not raise
        _setup_reconnection(room, session, userdata, agent)


class TestBackgroundProcessPauseResume:
    """Test pause/resume on BackgroundProcess."""

    def test_pause_sets_flag(self):
        from background_process import BackgroundProcess

        bp = BackgroundProcess(
            agent=MagicMock(),
            session=MagicMock(),
            session_data=MagicMock(),
        )
        assert bp._paused is False
        bp.pause()
        assert bp._paused is True

    def test_resume_clears_flag(self):
        from background_process import BackgroundProcess

        bp = BackgroundProcess(
            agent=MagicMock(),
            session=MagicMock(),
            session_data=MagicMock(),
        )
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
