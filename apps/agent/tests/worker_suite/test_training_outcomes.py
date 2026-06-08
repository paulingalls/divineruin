"""Tests for training completion: outcome building, narration cycles, push notifications."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from worker_suite._samples import SAMPLE_PLAYER

from async_worker_training import (
    advance_training_cycles,
    apply_skill_practice_advancement,
    build_training_completion_outcome,
)
from dialogue_parser import Segment
from training_rules import CompletionResult


def _txn_db():
    """A db-module stand-in whose transaction() yields a mock conn (no real DB).

    apply_skill_practice_advancement now runs the ledger claim + counter update in
    one db.transaction() (atomicity, debt b20815f92023); skill-path tests inject
    this so they stay hermetic.
    """
    conn = AsyncMock()

    @asynccontextmanager
    async def _transaction():
        yield conn

    module = MagicMock()
    module.transaction = _transaction
    return module


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
            patch(
                "async_worker_training.db_training.claim_training_accrual",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch("async_worker_training.db", _txn_db()),
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
            patch(
                "async_worker_training.db_training.claim_training_accrual",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch("async_worker_training.db", _txn_db()),
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
            patch(
                "async_worker_training.db_training.claim_training_accrual",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch("async_worker_training.db", _txn_db()),
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


SAMPLE_VARIANT_ACTIVITY = {
    "id": "train_var999",
    "player_id": "player_1",
    "activity_type": "technique_mentor_variant",
    "state": "running_second_half",
    "data": {
        "variant_id": "warrior_cleaving_blow_drathian",
        "ability_id": "warrior_cleaving_blow",
        "mentor_id": "guildmaster_torin",
        "decision_id": "power",
    },
    "transition_at": "2026-01-01T00:00:00Z",
}


def _variant_completion_patches(advance_result):
    """Common patches for driving a technique_mentor_variant completion."""
    seg = [Segment("GUILDMASTER_TORIN", "stern", "The form is yours.")]
    return (
        patch(
            "async_worker_training.db_training.get_due_training_transitions",
            new_callable=AsyncMock,
            return_value=[SAMPLE_VARIANT_ACTIVITY],
        ),
        patch("async_worker_training.db_training.update_training_activity", new_callable=AsyncMock),
        patch("async_worker_training.db_queries.get_player", new_callable=AsyncMock, return_value=SAMPLE_PLAYER),
        patch(
            "async_worker_training.mentor_variant_progress.advance_learning_cycle",
            new_callable=AsyncMock,
            return_value=advance_result,
        ),
        patch(
            "async_worker_training.generate_activity_narration",
            new_callable=AsyncMock,
            return_value=(seg, "The form is yours.", "Variant trained."),
        ),
        patch("async_worker_training.synthesize_segments", new_callable=AsyncMock, return_value="train_var999.mp3"),
        patch("async_worker_training.generate_notification_hook", new_callable=AsyncMock, return_value="Done."),
        patch("async_worker_training.send_push_notification", new_callable=AsyncMock),
    )


class TestMentorVariantCompletion:
    @pytest.mark.asyncio
    async def test_final_cycle_unlocks_and_clears_progress(self):
        """The cycle that reaches cycles_required records the unlock + deletes progress."""
        advance = {"cycles_completed": 3, "cycles_required": 3, "completed": True, "midpoint_decision_id": "power"}
        patches = _variant_completion_patches(advance)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3] as mock_advance,
            patches[4],
            patches[5],
            patches[6],
            patches[7],
            patch(
                "async_worker_training.mentor_variant_progress.record_unlocked", new_callable=AsyncMock
            ) as mock_unlock,
            patch(
                "async_worker_training.mentor_variant_progress.delete_learning_progress", new_callable=AsyncMock
            ) as mock_delete,
            patch(
                "async_worker_training.ability_persistence.set_active_variant", new_callable=AsyncMock
            ) as mock_activate,
        ):
            count = await advance_training_cycles()

        assert count == 1
        # advance was passed the activity_id (idempotency) + cycles_required 3.
        assert mock_advance.await_args is not None
        assert mock_advance.await_args.kwargs["activity_id"] == "train_var999"
        mock_unlock.assert_awaited_once_with("player_1", "warrior_cleaving_blow_drathian", midpoint_decision_id="power")
        mock_delete.assert_awaited_once_with("player_1", "warrior_cleaving_blow_drathian")
        # The unlocked variant is made the active override on its base technique (data.ability_id).
        mock_activate.assert_awaited_once_with("player_1", "warrior_cleaving_blow", "warrior_cleaving_blow_drathian")

    @pytest.mark.asyncio
    async def test_narration_failure_preserves_progress_for_idempotent_retry(self):
        """A completed variant whose narration fails must NOT delete the progress row.

        delete_learning_progress runs only after the narration is cached. If it ran
        before, a narration-failure retry would find no row and advance_learning_cycle
        would re-INSERT a phantom 1/N row for the already-unlocked variant (the
        last_activity_id guard can't protect a deleted row) — debt b20815f92023.
        """
        advance = {"cycles_completed": 3, "cycles_required": 3, "completed": True, "midpoint_decision_id": "power"}
        with (
            patch(
                "async_worker_training.db_training.get_due_training_transitions",
                new_callable=AsyncMock,
                return_value=[SAMPLE_VARIANT_ACTIVITY],
            ),
            patch("async_worker_training.db_training.update_training_activity", new_callable=AsyncMock) as mock_update,
            patch("async_worker_training.db_queries.get_player", new_callable=AsyncMock, return_value=SAMPLE_PLAYER),
            patch(
                "async_worker_training.mentor_variant_progress.advance_learning_cycle",
                new_callable=AsyncMock,
                return_value=advance,
            ),
            patch(
                "async_worker_training.generate_activity_narration",
                new_callable=AsyncMock,
                side_effect=RuntimeError("LLM down"),
            ),
            patch(
                "async_worker_training.mentor_variant_progress.record_unlocked", new_callable=AsyncMock
            ) as mock_unlock,
            patch(
                "async_worker_training.mentor_variant_progress.delete_learning_progress", new_callable=AsyncMock
            ) as mock_delete,
            patch(
                "async_worker_training.ability_persistence.set_active_variant", new_callable=AsyncMock
            ) as mock_activate,
        ):
            count = await advance_training_cycles()

        # Narration failed: activity not transitioned, no cache write, progress preserved.
        assert count == 0
        mock_update.assert_not_awaited()
        mock_delete.assert_not_awaited()
        # record_unlocked is idempotent (ON CONFLICT DO NOTHING) so running it pre-narration
        # is safe; the bug is purely the premature delete, which must not have happened.
        mock_unlock.assert_awaited_once()
        # set_active_variant also runs pre-narration; it is idempotent (ON CONFLICT DO UPDATE),
        # so a retry re-running it is harmless. It must have run exactly once on this attempt.
        mock_activate.assert_awaited_once_with("player_1", "warrior_cleaving_blow", "warrior_cleaving_blow_drathian")

    @pytest.mark.asyncio
    async def test_intermediate_cycle_does_not_unlock(self):
        """A cycle below cycles_required advances but does not unlock the variant."""
        advance = {"cycles_completed": 1, "cycles_required": 3, "completed": False, "midpoint_decision_id": None}
        patches = _variant_completion_patches(advance)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patches[6],
            patches[7],
            patch(
                "async_worker_training.mentor_variant_progress.record_unlocked", new_callable=AsyncMock
            ) as mock_unlock,
            patch(
                "async_worker_training.mentor_variant_progress.delete_learning_progress", new_callable=AsyncMock
            ) as mock_delete,
            patch(
                "async_worker_training.ability_persistence.set_active_variant", new_callable=AsyncMock
            ) as mock_activate,
        ):
            count = await advance_training_cycles()

        assert count == 1
        mock_unlock.assert_not_awaited()
        mock_delete.assert_not_awaited()
        # No unlock yet → no active-variant override set until training completes.
        mock_activate.assert_not_awaited()


class TestSkillAccrualIdempotency:
    @pytest.mark.asyncio
    async def test_skips_increment_when_already_claimed(self):
        """A retry whose accrual ledger claim fails must NOT re-increment the counter."""
        training = AsyncMock()
        training.claim_training_accrual = AsyncMock(return_value=False)
        with patch("async_worker_training.skill_persistence.apply_skill_use_with_persistence") as mock_apply:
            result = await apply_skill_practice_advancement(
                "player_1", "perception", 2, "train_x", db_mod=_txn_db(), training=training
            )
        assert result is None
        # claim runs inside the transaction with the shared conn.
        training.claim_training_accrual.assert_awaited_once()
        assert training.claim_training_accrual.await_args.args[0] == "train_x"
        mock_apply.assert_not_called()  # the shared counter is never touched on a retry

    @pytest.mark.asyncio
    async def test_applies_increment_on_fresh_claim(self):
        """A fresh claim applies the increment via the shared skill-use path."""
        training = AsyncMock()
        training.claim_training_accrual = AsyncMock(return_value=True)
        adv = MagicMock(advanced=True, new_tier="journeyman")
        with patch(
            "async_worker_training.skill_persistence.apply_skill_use_with_persistence",
            new_callable=AsyncMock,
            return_value=adv,
        ) as mock_apply:
            result = await apply_skill_practice_advancement(
                "player_1", "perception", 2, "train_y", db_mod=_txn_db(), training=training
            )
        assert result == {"advanced": True, "new_tier": "journeyman"}
        mock_apply.assert_awaited_once()
