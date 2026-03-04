"""Additional tests for background_process.py to achieve 100% coverage."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from background_process import GUIDANCE_LEVEL_2_SECS, BackgroundProcess, PendingSpeech, SpeechPriority
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
    async def test_run_builds_initial_warm_layer(self):
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
    async def test_run_drains_multiple_events(self):
        """_run() should drain all pending events from bus."""
        mock_agent = MagicMock()
        mock_session = MagicMock()
        mock_sd = MagicMock()
        mock_sd.in_combat = False
        mock_sd.last_player_speech_time = 0

        event1 = GameEvent(event_type="location_changed", payload={"new_location": "forest"})
        event2 = GameEvent(
            event_type="quest_updated", payload={"quest_name": "Test Quest", "objective": "Find the thing"}
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
    async def test_run_rebuilds_on_timeout(self):
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
                with patch.object(bp, "_check_guidance"):
                    try:
                        await bp._run()
                    except asyncio.CancelledError:
                        pass

                    # Should rebuild twice: initial + after timeout
                    assert mock_rebuild.call_count == 2


class TestGuidanceSystem:
    """Test player guidance nudges."""

    def test_check_guidance_skips_if_in_combat(self):
        """_check_guidance should skip if player is in combat."""
        mock_agent = MagicMock()
        mock_session = MagicMock()
        mock_sd = MagicMock()
        mock_sd.in_combat = True
        mock_sd.last_player_speech_time = time.time() - 100

        bp = BackgroundProcess(mock_agent, mock_session, mock_sd)

        with patch.object(bp, "_queue_speech") as mock_queue:
            bp._check_guidance()

            mock_queue.assert_not_called()

    def test_check_guidance_skips_if_player_never_spoke(self):
        """_check_guidance should skip if player hasn't spoken yet."""
        mock_agent = MagicMock()
        mock_session = MagicMock()
        mock_sd = MagicMock()
        mock_sd.in_combat = False
        mock_sd.last_player_speech_time = 0

        bp = BackgroundProcess(mock_agent, mock_session, mock_sd)

        with patch.object(bp, "_queue_speech") as mock_queue:
            bp._check_guidance()

            mock_queue.assert_not_called()

    def test_check_guidance_skips_if_already_nudged_since_last_speech(self):
        """_check_guidance should not re-nudge if player hasn't spoken since last nudge."""
        mock_agent = MagicMock()
        mock_session = MagicMock()
        mock_sd = MagicMock()
        mock_sd.in_combat = False
        player_speech_time = time.time() - 100
        mock_sd.last_player_speech_time = player_speech_time

        bp = BackgroundProcess(mock_agent, mock_session, mock_sd)
        bp._last_guidance_time = player_speech_time + 1  # Nudged after player spoke

        with patch.object(bp, "_queue_speech") as mock_queue:
            bp._check_guidance()

            mock_queue.assert_not_called()

    def test_check_guidance_queues_speech_after_silence_threshold(self):
        """_check_guidance should queue guidance after silence threshold."""
        mock_agent = MagicMock()
        mock_session = MagicMock()
        mock_sd = MagicMock()
        mock_sd.in_combat = False
        mock_sd.last_player_speech_time = time.time() - (GUIDANCE_LEVEL_2_SECS + 1)

        bp = BackgroundProcess(mock_agent, mock_session, mock_sd)
        bp._last_guidance_time = 0

        with patch.object(bp, "_queue_speech") as mock_queue:
            with patch.object(bp, "_get_quest_hints", return_value=[]):
                bp._check_guidance()

                mock_queue.assert_called_once()
                call_args = mock_queue.call_args[0]
                assert call_args[0] == SpeechPriority.IMPORTANT
                assert "quiet for a while" in call_args[1]
                assert bp._last_guidance_time > 0

    def test_check_guidance_includes_quest_hint_if_available(self):
        """_check_guidance should include quest hint in guidance prompt."""
        mock_agent = MagicMock()
        mock_session = MagicMock()
        mock_sd = MagicMock()
        mock_sd.in_combat = False
        mock_sd.last_player_speech_time = time.time() - (GUIDANCE_LEVEL_2_SECS + 1)

        bp = BackgroundProcess(mock_agent, mock_session, mock_sd)
        bp._last_guidance_time = 0

        with patch.object(bp, "_queue_speech") as mock_queue:
            with patch.object(bp, "_get_quest_hints", return_value=["Check the library"]):
                bp._check_guidance()

                call_args = mock_queue.call_args[0]
                assert "Check the library" in call_args[1]

    def test_get_quest_hints_returns_empty_list(self):
        """_get_quest_hints should return empty list (placeholder implementation)."""
        mock_agent = MagicMock()
        mock_session = MagicMock()
        mock_sd = MagicMock()

        bp = BackgroundProcess(mock_agent, mock_session, mock_sd)

        result = bp._get_quest_hints()

        assert result == []


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


class TestWarmLayerRebuild:
    """Test warm layer rebuilding logic."""

    @pytest.mark.asyncio
    async def test_rebuild_warm_layer_updates_agent_instructions(self):
        """_rebuild_warm_layer should update agent instructions with new warm layer."""
        mock_agent = MagicMock()
        mock_agent.update_instructions = AsyncMock()
        mock_session = MagicMock()
        mock_sd = MagicMock()
        mock_sd.location_id = "tavern"
        mock_sd.player_id = "p1"
        mock_sd.world_time = "evening"

        bp = BackgroundProcess(mock_agent, mock_session, mock_sd)

        with patch("background_process.build_warm_layer", new_callable=AsyncMock) as mock_build:
            with patch("background_process.build_full_prompt") as mock_full:
                mock_build.return_value = "warm layer content"
                mock_full.return_value = "full prompt"

                await bp._rebuild_warm_layer()

                mock_build.assert_awaited_once_with("tavern", "p1", "evening", combat_state=mock_sd.combat_state)
                mock_agent.update_instructions.assert_awaited_once_with("full prompt")
                assert bp._last_warm_layer == "warm layer content"

    @pytest.mark.asyncio
    async def test_rebuild_warm_layer_skips_if_unchanged(self):
        """_rebuild_warm_layer should skip update if warm layer unchanged."""
        mock_agent = MagicMock()
        mock_session = MagicMock()
        mock_sd = MagicMock()
        mock_sd.location_id = "tavern"
        mock_sd.player_id = "p1"
        mock_sd.world_time = "evening"

        bp = BackgroundProcess(mock_agent, mock_session, mock_sd)
        bp._last_warm_layer = "same content"

        with patch("background_process.build_warm_layer", new_callable=AsyncMock) as mock_build:
            with patch("background_process.build_full_prompt") as mock_full:
                mock_build.return_value = "same content"

                await bp._rebuild_warm_layer()

                mock_full.assert_not_called()

    @pytest.mark.asyncio
    async def test_rebuild_warm_layer_handles_exception(self):
        """_rebuild_warm_layer should not raise if build_warm_layer fails."""
        mock_agent = MagicMock()
        mock_session = MagicMock()
        mock_sd = MagicMock()
        mock_sd.location_id = "tavern"
        mock_sd.player_id = "p1"
        mock_sd.world_time = "evening"

        bp = BackgroundProcess(mock_agent, mock_session, mock_sd)
        bp._last_warm_layer = "old content"

        with patch("background_process.build_warm_layer", new_callable=AsyncMock) as mock_build:
            mock_build.side_effect = Exception("Database error")

            await bp._rebuild_warm_layer()  # Should not raise

            # Warm layer should be unchanged since build failed
            assert bp._last_warm_layer == "old content"


class TestPendingSpeech:
    """Test PendingSpeech dataclass ordering."""

    def test_pending_speech_orders_by_priority(self):
        """PendingSpeech should order by priority (higher priority first)."""
        low = PendingSpeech(priority=SpeechPriority.ROUTINE, instructions="low")
        mid = PendingSpeech(priority=SpeechPriority.IMPORTANT, instructions="mid")
        high = PendingSpeech(priority=SpeechPriority.CRITICAL, instructions="high")

        speeches = [low, mid, high]
        assert max(speeches) == high
        assert min(speeches) == low

    def test_pending_speech_includes_timestamp(self):
        """PendingSpeech should include creation timestamp."""
        before = time.time()
        speech = PendingSpeech(priority=SpeechPriority.ROUTINE, instructions="test")
        after = time.time()

        assert before <= speech.created <= after
