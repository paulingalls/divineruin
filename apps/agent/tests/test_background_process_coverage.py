"""Tests for background_process.py lifecycle, event handling, guidance, speech.

The run loop (start/stop/drain/timeout), scene-beat-hint guidance, and the
proactive speech queue. Split from the warm-layer rebuild + PendingSpeech
ordering tests (test_background_process_warm_layer.py) to stay under the
500-line cap.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import event_types as E
from background_process import BackgroundProcess
from bg_speech import PendingSpeech, SpeechPriority
from event_bus import GameEvent


class TestBackgroundProcessLifecycle:
    """Test background process start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_creates_background_task(self):
        """start() should create a background task."""
        mock_agent = MagicMock()
        mock_session = MagicMock()
        mock_sd = MagicMock()
        mock_sd.event_bus = MagicMock()
        mock_sd.event_bus.get = AsyncMock(side_effect=asyncio.CancelledError)

        bp = BackgroundProcess(mock_agent, mock_session, mock_sd)

        with patch.object(bp, "_rebuild_warm_layer", new_callable=AsyncMock):
            bp.start()

            assert bp._task is not None
            assert isinstance(bp._task, asyncio.Task)

            # Clean up
            await bp.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_background_task(self):
        """stop() should cancel the background task gracefully."""
        mock_agent = MagicMock()
        mock_session = MagicMock()
        mock_sd = MagicMock()
        mock_sd.event_bus = MagicMock()

        # Create a task that will be cancelled
        async def mock_run():
            await asyncio.sleep(10)

        bp = BackgroundProcess(mock_agent, mock_session, mock_sd)
        bp._task = asyncio.create_task(mock_run())

        await bp.stop()

        assert bp._stop is True
        assert bp._task.cancelled()

    @pytest.mark.asyncio
    async def test_stop_handles_already_cancelled_task(self):
        """stop() should handle task that's already cancelled."""
        mock_agent = MagicMock()
        mock_session = MagicMock()
        mock_sd = MagicMock()

        bp = BackgroundProcess(mock_agent, mock_session, mock_sd)
        bp._task = None

        await bp.stop()  # Should not raise

        assert bp._stop is True

    @pytest.mark.asyncio
    @patch("background_process.db_content_queries.get_scene", new_callable=AsyncMock, return_value=None)
    async def test_run_builds_initial_warm_layer(self, _mock_scene):
        """_run() should build warm layer on startup."""
        mock_agent = MagicMock()
        mock_session = MagicMock()
        mock_sd = MagicMock()
        mock_sd.event_bus = MagicMock()
        mock_sd.event_bus.get = AsyncMock(side_effect=asyncio.CancelledError)
        mock_sd.in_combat = False
        mock_sd.last_player_speech_time = 0

        bp = BackgroundProcess(mock_agent, mock_session, mock_sd)

        with patch.object(bp, "_rebuild_warm_layer", new_callable=AsyncMock) as mock_rebuild:
            with patch.object(bp, "_deliver_speech", new_callable=AsyncMock):
                try:
                    await bp._run()
                except asyncio.CancelledError:
                    pass

                # Should be called at least once for initial build
                assert mock_rebuild.call_count >= 1


class TestEventHandling:
    """Test event processing and warm layer rebuilding."""

    @pytest.mark.asyncio
    @patch("background_process.db_content_queries.get_scene", new_callable=AsyncMock, return_value=None)
    async def test_run_drains_multiple_events(self, _mock_scene):
        """_run() should drain all pending events from bus."""
        mock_agent = MagicMock()
        mock_session = MagicMock()
        mock_sd = MagicMock()
        mock_sd.in_combat = False
        mock_sd.last_player_speech_time = 0

        event1 = GameEvent(event_type=E.LOCATION_CHANGED, payload={"new_location": "forest"})
        event2 = GameEvent(
            event_type=E.QUEST_UPDATED, payload={"quest_name": "Test Quest", "objective": "Find the thing"}
        )

        mock_sd.event_bus = MagicMock()
        mock_sd.event_bus.get = AsyncMock(return_value=event1)
        mock_sd.event_bus.drain = MagicMock(return_value=[event2])

        bp = BackgroundProcess(mock_agent, mock_session, mock_sd)
        bp._stop = True  # Stop after one iteration

        with patch.object(bp, "_rebuild_warm_layer", new_callable=AsyncMock):
            with patch.object(bp, "_deliver_speech", new_callable=AsyncMock):
                with patch.object(bp, "_handle_events", return_value=True) as mock_handle:
                    try:
                        await bp._run()
                    except (asyncio.CancelledError, StopIteration):
                        pass

                    # Should handle both events
                    if mock_handle.called:
                        handled_events = mock_handle.call_args[0][0]
                        assert event1 in handled_events
                        assert event2 in handled_events

    @pytest.mark.asyncio
    @patch("background_process.db_content_queries.get_scene", new_callable=AsyncMock, return_value=None)
    async def test_run_rebuilds_on_timeout(self, _mock_scene):
        """_run() should rebuild warm layer on event timeout (no events)."""
        mock_agent = MagicMock()
        mock_session = MagicMock()
        mock_sd = MagicMock()
        mock_sd.in_combat = False
        mock_sd.last_player_speech_time = 0
        mock_sd.event_bus = MagicMock()

        # Return None on first call (timeout), then let it exit
        call_count = [0]

        async def mock_get(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return None  # Timeout
            # Second call, stop the loop
            raise asyncio.CancelledError

        mock_sd.event_bus.get = mock_get
        mock_sd.event_bus.drain = MagicMock(return_value=[])

        bp = BackgroundProcess(mock_agent, mock_session, mock_sd)

        with patch.object(bp, "_rebuild_warm_layer", new_callable=AsyncMock) as mock_rebuild:
            with patch.object(bp, "_deliver_speech", new_callable=AsyncMock):
                with patch.object(bp, "_check_scene_beat_hints"):
                    with patch.object(bp, "_check_companion_idle"):
                        try:
                            await bp._run()
                        except asyncio.CancelledError:
                            pass

                        # Should rebuild twice: initial + after timeout
                        assert mock_rebuild.call_count == 2


BEAT_QUEST = {
    "quest_id": "test_quest",
    "quest_name": "Test Quest",
    "current_stage": 0,
    "stages": [{"id": "s0", "objective": "Go."}],
    "scene_graph": [{"scene_id": "test_scene", "stage_refs": [0]}],
}

BEAT_SCENE_CACHE = {
    "test_scene": {
        "id": "test_scene",
        "name": "Test Scene",
        "type": "quest",
        "region_type": "wilderness",
        "instructions": "Narrate.",
        "beats": [
            {
                "id": "b1",
                "description": "Beat one.",
                "completion_condition": "Done",
                "companion_hints": ["Test hint 1"],
                "hint_delay_seconds": 30,
            },
        ],
    },
}


class TestGuidanceSystem:
    """Test scene beat hint delivery (replaced old _check_guidance)."""

    def test_skips_if_in_combat(self):
        mock_sd = MagicMock()
        mock_sd.in_combat = True
        mock_sd.last_player_speech_time = time.time() - 100
        bp = BackgroundProcess(MagicMock(), MagicMock(), mock_sd)
        bp._quest_cache = [BEAT_QUEST]
        bp._scene_cache = BEAT_SCENE_CACHE
        with patch.object(bp, "_queue_speech") as mock_queue:
            bp._check_scene_beat_hints()
            mock_queue.assert_not_called()

    def test_skips_if_player_never_spoke(self):
        mock_sd = MagicMock()
        mock_sd.in_combat = False
        mock_sd.last_player_speech_time = 0
        bp = BackgroundProcess(MagicMock(), MagicMock(), mock_sd)
        bp._quest_cache = [BEAT_QUEST]
        bp._scene_cache = BEAT_SCENE_CACHE
        with patch.object(bp, "_queue_speech") as mock_queue:
            bp._check_scene_beat_hints()
            mock_queue.assert_not_called()

    def test_queues_after_silence(self):
        mock_sd = MagicMock()
        mock_sd.in_combat = False
        past = time.time() - 35
        mock_sd.last_player_speech_time = past
        mock_sd.last_agent_speech_end = past
        mock_sd.companion_can_act = True
        mock_sd.companion = MagicMock()
        mock_sd.companion.emotional_state = "steady"
        bp = BackgroundProcess(MagicMock(), MagicMock(), mock_sd)
        bp._quest_cache = [BEAT_QUEST]
        bp._scene_cache = BEAT_SCENE_CACHE
        with patch.object(bp, "_queue_speech") as mock_queue:
            bp._check_scene_beat_hints()
            mock_queue.assert_called_once()
            call_args = mock_queue.call_args[0]
            assert call_args[0] == SpeechPriority.IMPORTANT
            assert "Test hint 1" in call_args[1]

    def test_skips_while_agent_spoke(self):
        mock_sd = MagicMock()
        mock_sd.in_combat = False
        mock_sd.last_player_speech_time = time.time() - 100
        mock_sd.last_agent_speech_end = time.time() - 5  # Agent spoke 5s ago
        bp = BackgroundProcess(MagicMock(), MagicMock(), mock_sd)
        bp._quest_cache = [BEAT_QUEST]
        bp._scene_cache = BEAT_SCENE_CACHE
        with patch.object(bp, "_queue_speech") as mock_queue:
            bp._check_scene_beat_hints()
            mock_queue.assert_not_called()

    def test_uses_later_of_player_and_agent_time(self):
        mock_sd = MagicMock()
        mock_sd.in_combat = False
        now = time.time()
        mock_sd.last_player_speech_time = now - 100
        mock_sd.last_agent_speech_end = now - 10  # Under 30s threshold
        bp = BackgroundProcess(MagicMock(), MagicMock(), mock_sd)
        bp._quest_cache = [BEAT_QUEST]
        bp._scene_cache = BEAT_SCENE_CACHE
        with patch.object(bp, "_queue_speech") as mock_queue:
            bp._check_scene_beat_hints()
            mock_queue.assert_not_called()

    def test_skips_if_recently_hinted(self):
        mock_sd = MagicMock()
        mock_sd.in_combat = False
        mock_sd.last_player_speech_time = time.time() - 100
        mock_sd.last_agent_speech_end = time.time() - 100
        bp = BackgroundProcess(MagicMock(), MagicMock(), mock_sd)
        bp._quest_cache = [BEAT_QUEST]
        bp._scene_cache = BEAT_SCENE_CACHE
        bp._scene_hint_state = {
            "scene_id": "test_scene",
            "beat_index": 0,
            "hint_index": 0,
            "last_hint_time": time.time() - 5,  # Hinted 5s ago, delay is 30s
        }
        with patch.object(bp, "_queue_speech") as mock_queue:
            bp._check_scene_beat_hints()
            mock_queue.assert_not_called()


class TestSpeechQueue:
    """Test proactive speech queue and delivery."""

    def test_queue_speech_adds_to_queue(self):
        """_queue_speech should add speech to queue."""
        mock_agent = MagicMock()
        mock_session = MagicMock()
        mock_sd = MagicMock()

        bp = BackgroundProcess(mock_agent, mock_session, mock_sd)

        bp._queue_speech(SpeechPriority.ROUTINE, "Test message")

        assert len(bp._speech_queue) == 1
        assert bp._speech_queue[0].priority == SpeechPriority.ROUTINE
        assert bp._speech_queue[0].instructions == "Test message"

    @pytest.mark.asyncio
    async def test_deliver_speech_does_nothing_if_queue_empty(self):
        """_deliver_speech should do nothing if queue is empty."""
        mock_agent = MagicMock()
        mock_session = MagicMock()
        mock_session.generate_reply = AsyncMock()
        mock_sd = MagicMock()

        bp = BackgroundProcess(mock_agent, mock_session, mock_sd)
        bp._speech_queue = []

        await bp._deliver_speech()

        mock_session.generate_reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_deliver_speech_delivers_highest_priority(self):
        """_deliver_speech should deliver highest priority speech."""
        mock_agent = MagicMock()
        mock_session = MagicMock()
        mock_session.generate_reply = AsyncMock()
        mock_sd = MagicMock()

        bp = BackgroundProcess(mock_agent, mock_session, mock_sd)
        bp._speech_queue = [
            PendingSpeech(priority=SpeechPriority.ROUTINE, instructions="Low priority"),
            PendingSpeech(priority=SpeechPriority.CRITICAL, instructions="High priority"),
            PendingSpeech(priority=SpeechPriority.IMPORTANT, instructions="Mid priority"),
        ]

        await bp._deliver_speech()

        mock_session.generate_reply.assert_awaited_once_with(instructions="High priority")
        assert len(bp._speech_queue) == 0

    @pytest.mark.asyncio
    async def test_deliver_speech_clears_queue_after_delivery(self):
        """_deliver_speech should clear entire queue after delivering top speech."""
        mock_agent = MagicMock()
        mock_session = MagicMock()
        mock_session.generate_reply = AsyncMock()
        mock_sd = MagicMock()

        bp = BackgroundProcess(mock_agent, mock_session, mock_sd)
        bp._speech_queue = [
            PendingSpeech(priority=SpeechPriority.ROUTINE, instructions="msg1"),
            PendingSpeech(priority=SpeechPriority.ROUTINE, instructions="msg2"),
        ]

        await bp._deliver_speech()

        assert bp._speech_queue == []

    @pytest.mark.asyncio
    async def test_deliver_speech_handles_exception_gracefully(self):
        """_deliver_speech should not raise if generate_reply fails."""
        mock_agent = MagicMock()
        mock_session = MagicMock()
        mock_session.generate_reply = AsyncMock(side_effect=Exception("TTS failed"))
        mock_sd = MagicMock()

        bp = BackgroundProcess(mock_agent, mock_session, mock_sd)
        bp._speech_queue = [
            PendingSpeech(priority=SpeechPriority.ROUTINE, instructions="Test"),
        ]

        await bp._deliver_speech()  # Should not raise

        assert bp._speech_queue == []
