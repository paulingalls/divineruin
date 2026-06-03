"""Tests for training completion: outcome building, narration cycles, push notifications."""

from unittest.mock import AsyncMock, patch

import pytest
from worker_suite._samples import SAMPLE_PLAYER

from async_worker_training import advance_training_cycles, build_training_completion_outcome
from dialogue_parser import Segment
from training_rules import CompletionResult

SAMPLE_TRAINING_DATA = {
    "mentor_id": "guildmaster_torin",
    "stat": "constitution",
    "skill": "perception",
    "dc": 12,
    "program_name": "Perception Drills",
}


class TestBuildTrainingCompletionOutcome:
    def test_breakthrough_on_skill_advanced(self):
        """When skill advances, tier should be 'breakthrough'."""
        completion = CompletionResult(state="complete", counter_increment=2, micro_bonus={"type": "fundamentals"})
        adv_info = {"advanced": True, "new_tier": "journeyman"}

        outcome = build_training_completion_outcome(completion, SAMPLE_TRAINING_DATA, adv_info)

        ctx = outcome["narrative_context"]
        assert ctx["tier"] == "breakthrough"
        assert ctx["mentor_id"] == "guildmaster_torin"
        assert ctx["training_stat"] == "constitution"
        assert ctx["training_skill"] == "perception"
        assert ctx["dc"] == 12
        assert outcome["stat_gains"]["skill_advanced"] is True
        assert outcome["stat_gains"]["new_tier"] == "journeyman"
        assert outcome["stat_gains"]["counter_increment"] == 2
        assert outcome["decision_options"] == []

    def test_plateau_for_non_skill_practice(self):
        """Non-skill_practice training with no advancement should be 'plateau'."""
        completion = CompletionResult(
            state="complete", counter_increment=0, micro_bonus={"type": "cast_speed", "value": -0.5}
        )
        data = {**SAMPLE_TRAINING_DATA, "skill": None}

        outcome = build_training_completion_outcome(completion, data, None)

        ctx = outcome["narrative_context"]
        assert ctx["tier"] == "plateau"
        assert outcome["stat_gains"]["skill_advanced"] is False
        assert outcome["stat_gains"]["new_tier"] is None
        assert outcome["stat_gains"]["counter_increment"] == 0
        assert outcome["stat_gains"]["micro_bonus"] == {"type": "cast_speed", "value": -0.5}


SAMPLE_TRAINING_ACTIVITY = {
    "id": "train_abc123",
    "player_id": "player_1",
    "activity_type": "skill_practice",
    "state": "running_second_half",
    "data": {
        "mentor_id": "guildmaster_torin",
        "stat": "wisdom",
        "skill": "perception",
        "dc": 12,
        "program_name": "Perception Drills",
        "decision_id": "fundamentals",
    },
    "transition_at": "2026-01-01T00:00:00Z",
}


class TestAdvanceTrainingCyclesNarration:
    @pytest.mark.asyncio
    async def test_completion_generates_narration_and_tts(self):
        """Second-half completion should generate narration, render TTS, and store both."""
        mock_segments = [Segment("GUILDMASTER_TORIN", "stern", "You've pushed through.")]

        with (
            patch(
                "async_worker_training.db_training.get_due_training_transitions",
                new_callable=AsyncMock,
                return_value=[SAMPLE_TRAINING_ACTIVITY],
            ),
            patch("async_worker_training.db_training.update_training_activity", new_callable=AsyncMock) as mock_update,
            patch("async_worker_training.db_queries.get_player", new_callable=AsyncMock, return_value=SAMPLE_PLAYER),
            patch(
                "async_worker_training.db_queries.get_single_skill_advancement",
                new_callable=AsyncMock,
                return_value={"tier": "novice", "use_counter": 3, "narrative_moment_ready": False},
            ),
            patch("async_worker_training.db_mutations.update_skill_advancement", new_callable=AsyncMock),
            patch(
                "async_worker_training.generate_activity_narration",
                new_callable=AsyncMock,
                return_value=(mock_segments, "You've pushed through.", "Training complete."),
            ) as mock_narration,
            patch(
                "async_worker_training.synthesize_segments",
                new_callable=AsyncMock,
                return_value="train_abc123.mp3",
            ) as mock_tts,
            patch(
                "async_worker_training.generate_notification_hook",
                new_callable=AsyncMock,
                return_value="Training done.",
            ),
            patch("async_worker_training.send_push_notification", new_callable=AsyncMock),
        ):
            count = await advance_training_cycles()

        assert count == 1

        # Narration was called with training_completion activity type
        narration_call = mock_narration.call_args
        outcome_arg = narration_call[0][0]
        assert outcome_arg["narrative_context"]["mentor_id"] == "guildmaster_torin"
        assert outcome_arg["narrative_context"]["training_stat"] == "wisdom"
        activity_arg = narration_call[0][2]
        assert activity_arg["activity_type"] == "training_completion"

        # TTS was called with the segments
        mock_tts.assert_awaited_once()
        tts_segments = mock_tts.call_args[0][0]
        assert tts_segments[0].character == "GUILDMASTER_TORIN"

        # Cache write then final write
        assert mock_update.await_count == 2
        # Cache write preserves narration
        cache_data = mock_update.call_args_list[0][0][2]
        assert cache_data["narration_text"] == "You've pushed through."
        assert cache_data["narration_summary"] == "Training complete."
        # Final write includes audio URL and state
        final_state = mock_update.call_args_list[1][0][1]
        assert final_state == "complete"
        final_data = mock_update.call_args_list[1][0][2]
        assert "narration_audio_url" in final_data

    @pytest.mark.asyncio
    async def test_narration_failure_does_not_transition(self):
        """If narration generation fails, training stays in running_second_half."""
        with (
            patch(
                "async_worker_training.db_training.get_due_training_transitions",
                new_callable=AsyncMock,
                return_value=[SAMPLE_TRAINING_ACTIVITY],
            ),
            patch("async_worker_training.db_training.update_training_activity", new_callable=AsyncMock) as mock_update,
            patch("async_worker_training.db_queries.get_player", new_callable=AsyncMock, return_value=SAMPLE_PLAYER),
            patch(
                "async_worker_training.db_queries.get_single_skill_advancement",
                new_callable=AsyncMock,
                return_value={"tier": "novice", "use_counter": 3, "narrative_moment_ready": False},
            ),
            patch("async_worker_training.db_mutations.update_skill_advancement", new_callable=AsyncMock),
            patch(
                "async_worker_training.generate_activity_narration",
                new_callable=AsyncMock,
                side_effect=RuntimeError("LLM down"),
            ),
        ):
            count = await advance_training_cycles()

        # Activity was NOT transitioned (exception caught, retry next cycle)
        assert count == 0
        mock_update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_tts_failure_caches_narration_but_does_not_complete(self):
        """If TTS fails after narration succeeds, narration is cached but state stays."""
        mock_segments = [Segment("GUILDMASTER_TORIN", "calm", "Well done.")]

        with (
            patch(
                "async_worker_training.db_training.get_due_training_transitions",
                new_callable=AsyncMock,
                return_value=[SAMPLE_TRAINING_ACTIVITY],
            ),
            patch("async_worker_training.db_training.update_training_activity", new_callable=AsyncMock) as mock_update,
            patch("async_worker_training.db_queries.get_player", new_callable=AsyncMock, return_value=SAMPLE_PLAYER),
            patch(
                "async_worker_training.db_queries.get_single_skill_advancement",
                new_callable=AsyncMock,
                return_value={"tier": "novice", "use_counter": 3, "narrative_moment_ready": False},
            ),
            patch("async_worker_training.db_mutations.update_skill_advancement", new_callable=AsyncMock),
            patch(
                "async_worker_training.generate_activity_narration",
                new_callable=AsyncMock,
                return_value=(mock_segments, "Well done.", "Summary."),
            ),
            patch(
                "async_worker_training.synthesize_segments",
                new_callable=AsyncMock,
                side_effect=RuntimeError("TTS down"),
            ),
        ):
            count = await advance_training_cycles()

        # Narration and advancement were cached but activity not completed
        assert count == 0
        mock_update.assert_awaited_once()
        cache_data = mock_update.call_args[0][2]
        assert cache_data["narration_text"] == "Well done."
        assert "narration_segments" in cache_data
        # Skill advancement info is cached to prevent double-application on retry
        assert "skill_advanced" in cache_data


SAMPLE_MIDPOINT_ACTIVITY = {
    "id": "train_mid1",
    "player_id": "player_1",
    "activity_type": "skill_practice",
    "state": "running_first_half",
    "data": {
        "program_name": "Perception Drills",
        "stat": "wisdom",
    },
    "transition_at": "2026-01-01T00:00:00Z",
}


class TestTrainingPushNotifications:
    @pytest.mark.asyncio
    async def test_midpoint_push_includes_program_name(self):
        """Midpoint notification title should include the program name."""
        with (
            patch(
                "async_worker_training.db_training.get_due_training_transitions",
                new_callable=AsyncMock,
                return_value=[SAMPLE_MIDPOINT_ACTIVITY],
            ),
            patch("async_worker_training.db_training.update_training_activity", new_callable=AsyncMock),
            patch("async_worker_training.send_push_notification", new_callable=AsyncMock) as mock_push,
        ):
            await advance_training_cycles()

        mock_push.assert_awaited_once()
        title = mock_push.call_args[0][1]
        assert "Perception Drills" in title
