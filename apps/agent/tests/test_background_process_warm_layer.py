"""Tests for background_process.py warm-layer rebuild + PendingSpeech ordering.

_rebuild_warm_layer (build, skip-if-unchanged, fail-soft) and the PendingSpeech
priority/timestamp dataclass. Split from the lifecycle/event/guidance/speech
tests (test_background_process_coverage.py) to stay under the 500-line cap; the
_mock_db_for_warm_layer helper rides here since only the rebuild tests use it.
"""

import time
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from background_process import BackgroundProcess
from bg_speech import PendingSpeech, SpeechPriority


@contextmanager
def _mock_db_for_warm_layer(quests=None, location=None, npcs=None, training=None):
    """Mock the DB calls used by _rebuild_warm_layer."""
    with patch(
        "background_process.db_queries.get_active_player_quests", new_callable=AsyncMock, return_value=quests or []
    ):
        with patch("background_process.db_content_queries.get_location", new_callable=AsyncMock, return_value=location):
            with patch(
                "background_process.db_queries.get_npcs_at_location", new_callable=AsyncMock, return_value=npcs or []
            ):
                with patch(
                    "background_process.db_training.get_player_training_activities",
                    new_callable=AsyncMock,
                    return_value=training or [],
                ):
                    yield


class TestWarmLayerRebuild:
    """Test warm layer rebuilding logic."""

    @pytest.mark.asyncio
    async def test_rebuild_warm_layer_updates_agent_instructions(self):
        """_rebuild_warm_layer should update agent instructions with new warm layer."""
        mock_agent = MagicMock()
        mock_agent.update_instructions = AsyncMock()
        mock_agent._agent_type = "city"
        mock_session = MagicMock()
        mock_sd = MagicMock()
        mock_sd.location_id = "tavern"
        mock_sd.player_id = "p1"
        mock_sd.world_time = "evening"

        bp = BackgroundProcess(mock_agent, mock_session, mock_sd)

        mock_location = {"name": "Tavern"}
        mock_npcs = [{"id": "npc1", "name": "Barkeep"}]

        with _mock_db_for_warm_layer(location=mock_location, npcs=mock_npcs):
            with patch("background_process.build_warm_layer", new_callable=AsyncMock) as mock_build:
                with patch("background_process.build_full_prompt") as mock_full:
                    mock_build.return_value = "warm layer content"
                    mock_full.return_value = "full prompt"

                    await bp._rebuild_warm_layer()

                    mock_build.assert_awaited_once_with(
                        "tavern",
                        "p1",
                        "evening",
                        combat_state=mock_sd.combat_state,
                        companion=mock_sd.companion,
                        quests=None,
                        corruption_level=mock_sd.corruption_level,
                        location=mock_location,
                        npcs_raw=mock_npcs,
                        scene_cache=None,
                        training=None,
                    )
                    mock_agent.update_instructions.assert_awaited_once_with("full prompt")
                    assert bp._last_warm_layer == "warm layer content"
                    # Verify caches were updated
                    assert mock_sd.cached_location_name == "Tavern"
                    assert mock_sd.cached_npc_names == ["Barkeep"]

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

        with _mock_db_for_warm_layer(location={"name": "Tavern"}):
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

        with _mock_db_for_warm_layer():
            with patch(
                "background_process.db_content_queries.get_location",
                new_callable=AsyncMock,
                side_effect=Exception("DB down"),
            ):
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
