"""Tests for the async background worker."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from async_worker import (
    _resolve_single_activity,
    advance_training_cycles,
    build_training_completion_outcome,
    resolve_due_activities,
)
from dialogue_parser import Segment
from training_rules import CompletionResult

SAMPLE_ACTIVITY = {
    "id": "activity_abc123",
    "player_id": "player_1",
    "status": "in_progress",
    "activity_type": "crafting",
    "parameters": {
        "recipe_id": "iron_sword",
        "result_item_id": "iron_sword",
        "result_item_name": "Iron Sword",
        "required_materials": ["iron_ingot", "leather_strip"],
        "skill": "arcana",
        "dc": 13,
        "npc_id": "grimjaw_blacksmith",
    },
    "resolve_at": "2026-01-01T00:00:00Z",
}

SAMPLE_PLAYER = {
    "name": "Aldric",
    "level": 3,
    "class": "warrior",
    "attributes": {
        "strength": 14,
        "dexterity": 12,
        "constitution": 13,
        "intelligence": 10,
        "wisdom": 11,
        "charisma": 8,
    },
    "proficiencies": ["athletics", "arcana"],
}


class TestResolveDueActivities:
    @pytest.mark.asyncio
    async def test_returns_zero_when_no_due_activities(self):
        with (
            patch("async_worker.db_activity_queries.get_due_activities", new_callable=AsyncMock, return_value=[]),
            patch("async_worker._backfill_progress_snippets", new_callable=AsyncMock),
        ):
            count = await resolve_due_activities()

        assert count == 0

    @pytest.mark.asyncio
    async def test_resolves_due_activities(self):
        with (
            patch(
                "async_worker.db_activity_queries.get_due_activities",
                new_callable=AsyncMock,
                return_value=[SAMPLE_ACTIVITY],
            ),
            patch("async_worker._resolve_single_activity", new_callable=AsyncMock) as mock_resolve,
            patch("async_worker._backfill_progress_snippets", new_callable=AsyncMock),
            patch("async_worker.generate_world_news", new_callable=AsyncMock),
        ):
            count = await resolve_due_activities()

        assert count == 1
        mock_resolve.assert_awaited_once_with(SAMPLE_ACTIVITY)

    @pytest.mark.asyncio
    async def test_continues_on_individual_failure(self):
        activities = [
            {**SAMPLE_ACTIVITY, "id": "act_1"},
            {**SAMPLE_ACTIVITY, "id": "act_2"},
        ]

        call_count = 0

        async def mock_resolve(activity):
            nonlocal call_count
            call_count += 1
            if activity["id"] == "act_1":
                raise RuntimeError("Transient failure")

        with (
            patch(
                "async_worker.db_activity_queries.get_due_activities", new_callable=AsyncMock, return_value=activities
            ),
            patch("async_worker._resolve_single_activity", side_effect=mock_resolve),
            patch("async_worker._backfill_progress_snippets", new_callable=AsyncMock),
            patch("async_worker.generate_world_news", new_callable=AsyncMock),
        ):
            count = await resolve_due_activities()

        assert call_count == 2
        assert count == 1  # Only act_2 succeeded


class TestResolveSingleActivity:
    @pytest.mark.asyncio
    async def test_crafting_resolution(self):
        with (
            patch("async_worker.db_queries.get_player", new_callable=AsyncMock, return_value=SAMPLE_PLAYER),
            patch(
                "async_worker.generate_activity_narration",
                new_callable=AsyncMock,
                return_value=(
                    [Segment("GRIMJAW_BLACKSMITH", "stern", "The blade sings.")],
                    "The blade sings.",
                    "Grimjaw is pleased with the blade.",
                ),
            ),
            patch("async_worker.synthesize_segments", new_callable=AsyncMock, return_value="activity_abc123.mp3"),
            patch("async_worker.db_mutations.update_activity", new_callable=AsyncMock) as mock_update,
            patch("async_worker.generate_notification_hook", new_callable=AsyncMock, return_value="Blade ready."),
            patch("async_worker.send_push_notification", new_callable=AsyncMock),
        ):
            await _resolve_single_activity(SAMPLE_ACTIVITY)

        assert mock_update.await_count == 2
        # First call: cache outcome + narration
        cache_call = mock_update.call_args_list[0]
        assert cache_call[0][0] == "activity_abc123"
        cached = cache_call[0][1]
        assert "outcome" in cached
        assert cached["narration_text"] == "The blade sings."
        assert cached["narration_summary"] == "Grimjaw is pleased with the blade."
        assert isinstance(cached["narration_segments"], list)
        assert cached["narration_segments"][0]["character"] == "GRIMJAW_BLACKSMITH"
        assert "decision_options" in cached
        # Second call: mark resolved with audio
        resolve_call = mock_update.call_args_list[1]
        resolved = resolve_call[0][1]
        assert resolved["status"] == "resolved"
        assert resolved["narration_audio_url"] == "/api/audio/activity_abc123.mp3"

    @pytest.mark.asyncio
    async def test_companion_errand_resolution(self):
        activity = {
            **SAMPLE_ACTIVITY,
            "activity_type": "companion_errand",
            "parameters": {
                "errand_type": "scout",
                "destination": "millhaven",
                "dc": 12,
            },
        }
        player_with_companion = {
            **SAMPLE_PLAYER,
            "companion": {
                "id": "companion_kael",
                "name": "Kael",
                "relationship_tier": 2,
                "attributes": {
                    "strength": 15,
                    "dexterity": 13,
                    "constitution": 14,
                    "intelligence": 10,
                    "wisdom": 12,
                    "charisma": 11,
                },
            },
        }

        with (
            patch("async_worker.db_queries.get_player", new_callable=AsyncMock, return_value=player_with_companion),
            patch(
                "async_worker.db_content_queries.get_location", new_callable=AsyncMock, return_value={"danger_level": 0}
            ),
            patch(
                "async_worker.generate_activity_narration",
                new_callable=AsyncMock,
                return_value=(
                    [Segment("COMPANION_KAEL", "neutral", "Kael returns.")],
                    "Kael returns.",
                    "Kael returns from scouting.",
                ),
            ),
            patch("async_worker.synthesize_segments", new_callable=AsyncMock, return_value="activity_abc123.mp3"),
            patch("async_worker.db_mutations.update_activity", new_callable=AsyncMock) as mock_update,
            patch("async_worker.generate_notification_hook", new_callable=AsyncMock, return_value="Kael returns."),
            patch("async_worker.send_push_notification", new_callable=AsyncMock),
        ):
            await _resolve_single_activity(activity)

        resolve_call = mock_update.call_args_list[1]
        assert resolve_call[0][1]["status"] == "resolved"
        cache_call = mock_update.call_args_list[0]
        assert cache_call[0][1]["outcome"]["errand_type"] == "scout"
        # Risk is rolled at resolution; safe destination -> "none".
        assert cache_call[0][1]["outcome"]["narrative_context"]["risk_outcome"] == "none"

    @pytest.mark.asyncio
    async def test_companion_errand_rolls_risk_at_resolution(self):
        # No risk_outcome in params: the worker rolls it at resolution from the
        # destination's danger level (dangerous), not from a pre-stored value.
        activity = {
            **SAMPLE_ACTIVITY,
            "activity_type": "companion_errand",
            "parameters": {"errand_type": "scout", "destination": "greyvale_ruins_entrance", "dc": 12},
        }
        player_with_companion = {**SAMPLE_PLAYER, "companion": {"id": "companion_kael", "name": "Kael"}}

        with (
            patch("async_worker.db_queries.get_player", new_callable=AsyncMock, return_value=player_with_companion),
            patch(
                "async_worker.db_content_queries.get_location", new_callable=AsyncMock, return_value={"danger_level": 2}
            ),
            patch("async_worker.roll_errand_risk", MagicMock(return_value="injured")) as mock_roll,
            patch(
                "async_worker.generate_activity_narration",
                new_callable=AsyncMock,
                return_value=([Segment("COMPANION_KAEL", "neutral", "x")], "x", "x"),
            ),
            patch("async_worker.synthesize_segments", new_callable=AsyncMock, return_value="a.mp3"),
            patch("async_worker.db_mutations.update_activity", new_callable=AsyncMock) as mock_update,
            patch("async_worker.generate_notification_hook", new_callable=AsyncMock, return_value="x"),
            patch("async_worker.send_push_notification", new_callable=AsyncMock),
        ):
            await _resolve_single_activity(activity)

        # Rolled with the resolved danger level + companion, not a stored value.
        assert mock_roll.call_count == 1
        kwargs = mock_roll.call_args.kwargs
        args = mock_roll.call_args.args
        called = {**dict(zip(("errand_type", "danger_level", "companion_id"), args, strict=False)), **kwargs}
        assert called["errand_type"] == "scout"
        assert called["danger_level"] == "dangerous"
        assert called["companion_id"] == "companion_kael"
        assert mock_update.call_args_list[0][0][1]["outcome"]["narrative_context"]["risk_outcome"] == "injured"

    @pytest.mark.asyncio
    async def test_companion_errand_missing_location_defaults_safe(self):
        activity = {
            **SAMPLE_ACTIVITY,
            "activity_type": "companion_errand",
            "parameters": {"errand_type": "scout", "destination": "nowhere", "dc": 12},
        }
        player_with_companion = {**SAMPLE_PLAYER, "companion": {"id": "companion_kael", "name": "Kael"}}

        with (
            patch("async_worker.db_queries.get_player", new_callable=AsyncMock, return_value=player_with_companion),
            patch("async_worker.db_content_queries.get_location", new_callable=AsyncMock, return_value=None),
            patch("async_worker.roll_errand_risk", MagicMock(return_value="none")) as mock_roll,
            patch(
                "async_worker.generate_activity_narration",
                new_callable=AsyncMock,
                return_value=([Segment("COMPANION_KAEL", "neutral", "x")], "x", "x"),
            ),
            patch("async_worker.synthesize_segments", new_callable=AsyncMock, return_value="a.mp3"),
            patch("async_worker.db_mutations.update_activity", new_callable=AsyncMock),
            patch("async_worker.generate_notification_hook", new_callable=AsyncMock, return_value="x"),
            patch("async_worker.send_push_notification", new_callable=AsyncMock),
        ):
            await _resolve_single_activity(activity)

        # Missing/unresolvable destination defaults to "safe" (not a crash).
        args = mock_roll.call_args.args
        kwargs = mock_roll.call_args.kwargs
        called = {**dict(zip(("errand_type", "danger_level", "companion_id"), args, strict=False)), **kwargs}
        assert called["danger_level"] == "safe"

    @pytest.mark.asyncio
    async def test_does_not_update_on_narration_failure(self):
        """If narration fails, the activity stays in_progress for retry."""
        with (
            patch("async_worker.db_queries.get_player", new_callable=AsyncMock, return_value=SAMPLE_PLAYER),
            patch(
                "async_worker.generate_activity_narration", new_callable=AsyncMock, side_effect=RuntimeError("LLM down")
            ),
            patch("async_worker.db_mutations.update_activity", new_callable=AsyncMock) as mock_update,
        ):
            with pytest.raises(RuntimeError):
                await _resolve_single_activity(SAMPLE_ACTIVITY)

        mock_update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_caches_narration_on_tts_failure(self):
        """If TTS fails, outcome and narration are cached but status stays in_progress."""
        with (
            patch("async_worker.db_queries.get_player", new_callable=AsyncMock, return_value=SAMPLE_PLAYER),
            patch(
                "async_worker.generate_activity_narration",
                new_callable=AsyncMock,
                return_value=(
                    [Segment("DM_NARRATOR", "neutral", "Text.")],
                    "Text.",
                    "Summary.",
                ),
            ),
            patch("async_worker.synthesize_segments", new_callable=AsyncMock, side_effect=RuntimeError("TTS down")),
            patch("async_worker.db_mutations.update_activity", new_callable=AsyncMock) as mock_update,
        ):
            with pytest.raises(RuntimeError):
                await _resolve_single_activity(SAMPLE_ACTIVITY)

        # Cache write should happen, but not the resolve write
        mock_update.assert_awaited_once()
        cached = mock_update.call_args[0][1]
        assert "outcome" in cached
        assert cached["narration_text"] == "Text."
        assert cached["narration_summary"] == "Summary."
        assert isinstance(cached["narration_segments"], list)
        assert "status" not in cached

    @pytest.mark.asyncio
    async def test_handles_missing_player_data(self):
        """Should still work with empty player data."""
        with (
            patch("async_worker.db_queries.get_player", new_callable=AsyncMock, return_value=None),
            patch(
                "async_worker.generate_activity_narration",
                new_callable=AsyncMock,
                return_value=(
                    [Segment("DM_NARRATOR", "neutral", "Narration.")],
                    "Narration.",
                    "Summary.",
                ),
            ),
            patch("async_worker.synthesize_segments", new_callable=AsyncMock, return_value="activity_abc123.mp3"),
            patch("async_worker.db_mutations.update_activity", new_callable=AsyncMock) as mock_update,
            patch("async_worker.generate_notification_hook", new_callable=AsyncMock, return_value="Update."),
            patch("async_worker.send_push_notification", new_callable=AsyncMock),
        ):
            await _resolve_single_activity(SAMPLE_ACTIVITY)

        assert mock_update.await_count == 2
        resolve_call = mock_update.call_args_list[1]
        assert resolve_call[0][1]["status"] == "resolved"


# --- check_god_whisper_triggers ---


class TestCheckGodWhisperTriggers:
    @pytest.mark.asyncio
    @patch("async_worker.db_mutations.mark_favor_whisper_level", new_callable=AsyncMock)
    @patch("god_whisper_generator.generate_god_whisper", new_callable=AsyncMock, return_value="whisper_1")
    @patch("async_worker.db_activity_queries.get_pending_god_whispers", new_callable=AsyncMock, return_value=[])
    @patch("async_worker.db.get_pool")
    async def test_generates_whisper_above_threshold(self, mock_pool, mock_pending, mock_gen, mock_mark):
        import json

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(
            return_value=[
                {
                    "player_id": "player_1",
                    "favor": json.dumps(
                        {
                            "patron": "kaelen",
                            "level": 25,
                            "max": 100,
                            "last_whisper_level": 0,
                        }
                    ),
                }
            ]
        )
        mock_pool.return_value = mock_conn

        from async_worker import check_god_whisper_triggers

        count = await check_god_whisper_triggers()
        assert count == 1
        mock_gen.assert_called_once_with("player_1", "kaelen")
        mock_mark.assert_called_once_with("player_1", 25)

    @pytest.mark.asyncio
    @patch("async_worker.db.get_pool")
    async def test_skips_below_cooldown(self, mock_pool):
        import json

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(
            return_value=[
                {
                    "player_id": "player_1",
                    "favor": json.dumps(
                        {
                            "patron": "kaelen",
                            "level": 35,
                            "max": 100,
                            "last_whisper_level": 25,
                        }
                    ),
                }
            ]
        )
        mock_pool.return_value = mock_conn

        from async_worker import check_god_whisper_triggers

        count = await check_god_whisper_triggers()
        # 35 - 25 = 10 < 25 cooldown
        assert count == 0

    @pytest.mark.asyncio
    @patch("async_worker.db.get_pool")
    async def test_no_players_returns_zero(self, mock_pool):
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_pool.return_value = mock_conn

        from async_worker import check_god_whisper_triggers

        count = await check_god_whisper_triggers()
        assert count == 0


# --- build_training_completion_outcome ---


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


# --- advance_training_cycles (narration integration) ---


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
                "async_worker.db_training.get_due_training_transitions",
                new_callable=AsyncMock,
                return_value=[SAMPLE_TRAINING_ACTIVITY],
            ),
            patch("async_worker.db_training.update_training_activity", new_callable=AsyncMock) as mock_update,
            patch("async_worker.db_queries.get_player", new_callable=AsyncMock, return_value=SAMPLE_PLAYER),
            patch(
                "async_worker.db_queries.get_single_skill_advancement",
                new_callable=AsyncMock,
                return_value={"tier": "novice", "use_counter": 3, "narrative_moment_ready": False},
            ),
            patch("async_worker.db_mutations.update_skill_advancement", new_callable=AsyncMock),
            patch(
                "async_worker.generate_activity_narration",
                new_callable=AsyncMock,
                return_value=(mock_segments, "You've pushed through.", "Training complete."),
            ) as mock_narration,
            patch(
                "async_worker.synthesize_segments",
                new_callable=AsyncMock,
                return_value="train_abc123.mp3",
            ) as mock_tts,
            patch("async_worker.generate_notification_hook", new_callable=AsyncMock, return_value="Training done."),
            patch("async_worker.send_push_notification", new_callable=AsyncMock),
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
                "async_worker.db_training.get_due_training_transitions",
                new_callable=AsyncMock,
                return_value=[SAMPLE_TRAINING_ACTIVITY],
            ),
            patch("async_worker.db_training.update_training_activity", new_callable=AsyncMock) as mock_update,
            patch("async_worker.db_queries.get_player", new_callable=AsyncMock, return_value=SAMPLE_PLAYER),
            patch(
                "async_worker.db_queries.get_single_skill_advancement",
                new_callable=AsyncMock,
                return_value={"tier": "novice", "use_counter": 3, "narrative_moment_ready": False},
            ),
            patch("async_worker.db_mutations.update_skill_advancement", new_callable=AsyncMock),
            patch(
                "async_worker.generate_activity_narration",
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
                "async_worker.db_training.get_due_training_transitions",
                new_callable=AsyncMock,
                return_value=[SAMPLE_TRAINING_ACTIVITY],
            ),
            patch("async_worker.db_training.update_training_activity", new_callable=AsyncMock) as mock_update,
            patch("async_worker.db_queries.get_player", new_callable=AsyncMock, return_value=SAMPLE_PLAYER),
            patch(
                "async_worker.db_queries.get_single_skill_advancement",
                new_callable=AsyncMock,
                return_value={"tier": "novice", "use_counter": 3, "narrative_moment_ready": False},
            ),
            patch("async_worker.db_mutations.update_skill_advancement", new_callable=AsyncMock),
            patch(
                "async_worker.generate_activity_narration",
                new_callable=AsyncMock,
                return_value=(mock_segments, "Well done.", "Summary."),
            ),
            patch(
                "async_worker.synthesize_segments",
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


# --- Push notification polish (story-006) ---


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
                "async_worker.db_training.get_due_training_transitions",
                new_callable=AsyncMock,
                return_value=[SAMPLE_MIDPOINT_ACTIVITY],
            ),
            patch("async_worker.db_training.update_training_activity", new_callable=AsyncMock),
            patch("async_worker.send_push_notification", new_callable=AsyncMock) as mock_push,
        ):
            await advance_training_cycles()

        mock_push.assert_awaited_once()
        title = mock_push.call_args[0][1]
        assert "Perception Drills" in title
