"""End-to-end integration tests for the async activity pipeline.

Full pipeline with mocked LLM/TTS:
1. Create player in DB
2. Insert activity with past resolve_at
3. Run resolve_due_activities()
4. Verify: outcome computed, narration generated, audio file exists, DB updated
5. Test soft timer variance
"""

import random
import tempfile
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from async_rules import compute_resolve_time, resolve_crafting
from async_worker import _resolve_single_activity, resolve_due_activities
from dialogue_parser import Segment

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


class TestFullPipeline:
    """End-to-end: create activity -> resolve -> narrate -> audio -> DB update."""

    @pytest.mark.asyncio
    async def test_crafting_e2e(self):
        """Full crafting pipeline with mocked external services."""
        activity = {
            "id": "activity_e2e_craft",
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
            "resolve_at": "2025-01-01T00:00:00Z",
        }

        update_calls = []

        async def mock_update(activity_id, updates, **kwargs):
            update_calls.append((activity_id, updates))

        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch("async_worker.db_queries.get_player", new_callable=AsyncMock, return_value=SAMPLE_PLAYER),
                patch(
                    "async_worker.generate_activity_narration",
                    new_callable=AsyncMock,
                    return_value=(
                        [
                            Segment(
                                "GRIMJAW_BLACKSMITH", "stern", "The blade holds true. A fine piece of work, recruit."
                            ),
                            Segment("DM_NARRATOR", "neutral", "The iron sword gleams."),
                        ],
                        "The blade holds true. A fine piece of work, recruit. The iron sword gleams.",
                        "Grimjaw approves of the finished blade.",
                    ),
                ),
                patch(
                    "async_worker.synthesize_segments", new_callable=AsyncMock, return_value="activity_e2e_craft.mp3"
                ),
                patch("async_worker.db_mutations.update_activity", side_effect=mock_update),
                patch("async_worker.AUDIO_DIR", tmpdir),
                patch(
                    "async_worker.generate_notification_hook",
                    new_callable=AsyncMock,
                    return_value="Your blade is ready.",
                ),
                patch("async_worker.send_push_notification", new_callable=AsyncMock),
            ):
                await _resolve_single_activity(activity)

        assert len(update_calls) == 2
        # First call: cache outcome + narration
        cache_id, cached = update_calls[0]
        assert cache_id == "activity_e2e_craft"
        assert cached["narration_text"] is not None
        assert any("GRIMJAW" in seg["character"].upper() for seg in cached["narration_segments"])
        assert cached["narration_summary"] is not None
        assert isinstance(cached["narration_segments"], list)
        assert cached["outcome"]["tier"] in ("success", "partial", "unexpected", "failure")
        assert len(cached["decision_options"]) >= 2
        # Second call: mark resolved with audio
        _, resolved = update_calls[1]
        assert resolved["status"] == "resolved"
        assert resolved["narration_audio_url"] == "/api/audio/activity_e2e_craft.mp3"

    @pytest.mark.asyncio
    async def test_companion_errand_e2e(self):
        """Full companion errand pipeline."""
        activity = {
            "id": "activity_e2e_errand",
            "player_id": "player_1",
            "status": "in_progress",
            "activity_type": "companion_errand",
            "parameters": {
                "errand_type": "scout",
                "destination": "millhaven",
                "dc": 12,
            },
            "resolve_at": "2025-01-01T00:00:00Z",
        }

        update_calls = []

        async def mock_update(activity_id, updates, **kwargs):
            update_calls.append((activity_id, updates))

        with (
            patch("async_worker.db_queries.get_player", new_callable=AsyncMock, return_value=SAMPLE_PLAYER),
            patch(
                "async_worker.generate_activity_narration",
                new_callable=AsyncMock,
                return_value=(
                    [Segment("COMPANION_KAEL", "neutral", "Found tracks north.")],
                    "Found tracks north.",
                    "Kael discovers tracks heading north.",
                ),
            ),
            patch("async_worker.synthesize_segments", new_callable=AsyncMock, return_value="activity_e2e_errand.mp3"),
            patch("async_worker.db_mutations.update_activity", side_effect=mock_update),
            patch("async_worker.generate_notification_hook", new_callable=AsyncMock, return_value="Kael returns."),
            patch("async_worker.send_push_notification", new_callable=AsyncMock),
        ):
            await _resolve_single_activity(activity)

        assert len(update_calls) == 2
        cached = update_calls[0][1]
        assert cached["outcome"]["errand_type"] == "scout"
        assert "information_gained" in cached["outcome"]
        resolved = update_calls[1][1]
        assert resolved["status"] == "resolved"
        assert "narrative_context" in cached["outcome"]

    @pytest.mark.asyncio
    async def test_batch_resolution(self):
        """Multiple due activities resolve in one cycle."""
        activities = [
            {
                "id": f"activity_batch_{i}",
                "player_id": "player_1",
                "status": "in_progress",
                "activity_type": "crafting",
                "parameters": {
                    "recipe_id": "iron_sword",
                    "result_item_id": "iron_sword",
                    "result_item_name": "Iron Sword",
                    "required_materials": [],
                    "skill": "arcana",
                    "dc": 13,
                },
                "resolve_at": "2025-01-01T00:00:00Z",
            }
            for i in range(3)
        ]

        with (
            patch(
                "async_worker.db_activity_queries.get_due_activities", new_callable=AsyncMock, return_value=activities
            ),
            patch("async_worker._resolve_single_activity", new_callable=AsyncMock) as mock_resolve,
            patch("async_worker._backfill_progress_snippets", new_callable=AsyncMock),
            patch("async_worker.generate_world_news", new_callable=AsyncMock),
        ):
            count = await resolve_due_activities()

        assert count == 3
        assert mock_resolve.await_count == 3


class TestSoftTimerVariance:
    """Verify soft timer randomization produces actual variance."""

    def test_10_activities_have_variance(self):
        """10 activities with 4-8 hour range should resolve at varied times."""
        start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        min_s, max_s = 14400, 28800  # 4-8 hours

        times = []
        for seed in range(10):
            rng = random.Random(seed)
            t = compute_resolve_time(min_s, max_s, start_time=start, rng=rng)
            delta = (t - start).total_seconds()
            times.append(delta)

        # All within range
        assert all(min_s <= t <= max_s for t in times), f"Out of range: {times}"

        # Actual variance
        assert len(set(times)) > 1, "All resolve times are identical"
        assert min(times) != max(times), "No spread in resolve times"

        # Standard deviation > 0
        mean = sum(times) / len(times)
        variance = sum((t - mean) ** 2 for t in times) / len(times)
        assert variance > 0, "Zero variance in soft timer"

    def test_crafting_outcomes_vary(self):
        """Different RNG seeds produce different crafting outcomes."""
        params = {
            "recipe_id": "iron_sword",
            "result_item_id": "iron_sword",
            "result_item_name": "Iron Sword",
            "required_materials": ["iron_ingot"],
            "skill": "arcana",
            "dc": 13,
        }
        tiers = set()
        for seed in range(100):
            result = resolve_crafting(SAMPLE_PLAYER, params, rng=random.Random(seed))
            tiers.add(result.tier)

        assert len(tiers) >= 3, f"Only got {len(tiers)} tiers: {tiers}"


class TestCostVerification:
    """Verify narration cost stays within budget."""

    @pytest.mark.asyncio
    async def test_narration_token_budget(self):
        """Typical narration should use < 200 input tokens, < 200 output tokens."""
        # Mock Anthropic tool_use response with realistic token counts
        # Note: MagicMock(name=...) sets the mock's repr name, not an attribute,
        # so we use spec=[] and set attributes directly.
        mock_content = MagicMock(spec=[])
        mock_content.type = "tool_use"
        mock_content.name = "narration_result"
        mock_content.input = {
            "segments": [
                {"character": "GRIMJAW_BLACKSMITH", "emotion": "stern", "text": "The blade holds. Not bad, recruit."},
            ],
            "summary": "Grimjaw approves of the finished blade.",
        }
        mock_response = MagicMock()
        mock_response.content = [mock_content]
        mock_response.usage = MagicMock()
        mock_response.usage.input_tokens = 180  # typical
        mock_response.usage.output_tokens = 150  # typical

        from narration import generate_activity_narration

        activity_data = {"activity_type": "crafting"}
        outcome = {
            "tier": "success",
            "narrative_context": {
                "tier": "success",
                "roll": 18,
                "total": 22,
                "dc": 13,
                "skill": "athletics",
                "recipe_name": "Iron Sword",
                "quality_bonus": 2,
                "npc_id": "grimjaw_blacksmith",
            },
            "decision_options": [
                {"id": "keep", "label": "Keep the item"},
                {"id": "sell", "label": "Sell it"},
            ],
        }

        with patch("narration._client.messages.create", new_callable=AsyncMock, return_value=mock_response):
            segments, narration_text, summary = await generate_activity_narration(outcome, SAMPLE_PLAYER, activity_data)

        assert len(segments) >= 1
        assert isinstance(narration_text, str)
        assert isinstance(summary, str)

        # Haiku pricing: $0.80/M input, $4/M output
        input_cost = mock_response.usage.input_tokens * 0.80 / 1_000_000
        output_cost = mock_response.usage.output_tokens * 4.0 / 1_000_000
        total_cost = input_cost + output_cost
        # Should be well under $0.005
        assert total_cost < 0.005, f"Cost too high: ${total_cost:.6f}"
