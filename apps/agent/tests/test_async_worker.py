"""Tests for the async background worker."""

from unittest.mock import AsyncMock, patch

import pytest

from async_worker import _resolve_single_activity, resolve_due_activities

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
            patch("async_worker.db.get_due_activities", new_callable=AsyncMock, return_value=[]),
            patch("async_worker._backfill_progress_snippets", new_callable=AsyncMock),
        ):
            count = await resolve_due_activities()

        assert count == 0

    @pytest.mark.asyncio
    async def test_resolves_due_activities(self):
        with (
            patch("async_worker.db.get_due_activities", new_callable=AsyncMock, return_value=[SAMPLE_ACTIVITY]),
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
            patch("async_worker.db.get_due_activities", new_callable=AsyncMock, return_value=activities),
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
            patch("async_worker.db.get_player", new_callable=AsyncMock, return_value=SAMPLE_PLAYER),
            patch(
                "async_worker.generate_activity_narration",
                new_callable=AsyncMock,
                return_value="[NPC:Grimjaw] The blade sings.",
            ),
            patch("async_worker.synthesize_to_file", new_callable=AsyncMock, return_value="activity_abc123.mp3"),
            patch("async_worker.db.update_activity", new_callable=AsyncMock) as mock_update,
            patch("async_worker.generate_notification_hook", new_callable=AsyncMock, return_value="Blade ready."),
            patch("async_worker.send_push_notification", new_callable=AsyncMock),
        ):
            await _resolve_single_activity(SAMPLE_ACTIVITY)

        mock_update.assert_awaited_once()
        call_args = mock_update.call_args
        assert call_args[0][0] == "activity_abc123"
        updates = call_args[0][1]
        assert updates["status"] == "resolved"
        assert updates["narration_text"] == "[NPC:Grimjaw] The blade sings."
        assert updates["narration_audio_url"] == "/api/audio/activity_abc123.mp3"
        assert "outcome" in updates
        assert "decision_options" in updates

    @pytest.mark.asyncio
    async def test_training_resolution(self):
        activity = {
            **SAMPLE_ACTIVITY,
            "activity_type": "training",
            "parameters": {
                "program_id": "combat_basics",
                "stat": "strength",
                "dc": 13,
                "mentor_id": "guildmaster_torin",
            },
        }

        with (
            patch("async_worker.db.get_player", new_callable=AsyncMock, return_value=SAMPLE_PLAYER),
            patch(
                "async_worker.generate_activity_narration", new_callable=AsyncMock, return_value="Training narration."
            ),
            patch("async_worker.synthesize_to_file", new_callable=AsyncMock, return_value="activity_abc123.mp3"),
            patch("async_worker.db.update_activity", new_callable=AsyncMock) as mock_update,
            patch("async_worker.generate_notification_hook", new_callable=AsyncMock, return_value="Training done."),
            patch("async_worker.send_push_notification", new_callable=AsyncMock),
        ):
            await _resolve_single_activity(activity)

        updates = mock_update.call_args[0][1]
        assert updates["status"] == "resolved"
        assert updates["outcome"]["tier"] in ("breakthrough", "plateau", "redirection")

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
            patch("async_worker.db.get_player", new_callable=AsyncMock, return_value=player_with_companion),
            patch("async_worker.generate_activity_narration", new_callable=AsyncMock, return_value="Kael returns."),
            patch("async_worker.synthesize_to_file", new_callable=AsyncMock, return_value="activity_abc123.mp3"),
            patch("async_worker.db.update_activity", new_callable=AsyncMock) as mock_update,
            patch("async_worker.generate_notification_hook", new_callable=AsyncMock, return_value="Kael returns."),
            patch("async_worker.send_push_notification", new_callable=AsyncMock),
        ):
            await _resolve_single_activity(activity)

        updates = mock_update.call_args[0][1]
        assert updates["status"] == "resolved"
        assert updates["outcome"]["errand_type"] == "scout"

    @pytest.mark.asyncio
    async def test_does_not_update_on_narration_failure(self):
        """If narration fails, the activity stays in_progress for retry."""
        with (
            patch("async_worker.db.get_player", new_callable=AsyncMock, return_value=SAMPLE_PLAYER),
            patch(
                "async_worker.generate_activity_narration", new_callable=AsyncMock, side_effect=RuntimeError("LLM down")
            ),
            patch("async_worker.db.update_activity", new_callable=AsyncMock) as mock_update,
        ):
            with pytest.raises(RuntimeError):
                await _resolve_single_activity(SAMPLE_ACTIVITY)

        mock_update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_does_not_update_on_tts_failure(self):
        """If TTS fails, the activity stays in_progress for retry."""
        with (
            patch("async_worker.db.get_player", new_callable=AsyncMock, return_value=SAMPLE_PLAYER),
            patch("async_worker.generate_activity_narration", new_callable=AsyncMock, return_value="Text."),
            patch("async_worker.synthesize_to_file", new_callable=AsyncMock, side_effect=RuntimeError("TTS down")),
            patch("async_worker.db.update_activity", new_callable=AsyncMock) as mock_update,
        ):
            with pytest.raises(RuntimeError):
                await _resolve_single_activity(SAMPLE_ACTIVITY)

        mock_update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handles_missing_player_data(self):
        """Should still work with empty player data."""
        with (
            patch("async_worker.db.get_player", new_callable=AsyncMock, return_value=None),
            patch("async_worker.generate_activity_narration", new_callable=AsyncMock, return_value="Narration."),
            patch("async_worker.synthesize_to_file", new_callable=AsyncMock, return_value="activity_abc123.mp3"),
            patch("async_worker.db.update_activity", new_callable=AsyncMock) as mock_update,
            patch("async_worker.generate_notification_hook", new_callable=AsyncMock, return_value="Update."),
            patch("async_worker.send_push_notification", new_callable=AsyncMock),
        ):
            await _resolve_single_activity(SAMPLE_ACTIVITY)

        mock_update.assert_awaited_once()
        updates = mock_update.call_args[0][1]
        assert updates["status"] == "resolved"


# --- check_god_whisper_triggers ---


class TestCheckGodWhisperTriggers:
    @pytest.mark.asyncio
    @patch("async_worker.db.mark_favor_whisper_level", new_callable=AsyncMock)
    @patch("god_whisper_generator.generate_god_whisper", new_callable=AsyncMock, return_value="whisper_1")
    @patch("async_worker.db.get_pending_god_whispers", new_callable=AsyncMock, return_value=[])
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
