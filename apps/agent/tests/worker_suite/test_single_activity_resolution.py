"""Tests for _resolve_single_activity — claim/narrate/TTS/mark lifecycle per activity."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from claim_stack_helpers import patch_claim_stack
from sample_fixtures import mock_txn
from worker_suite._samples import SAMPLE_ACTIVITY, SAMPLE_PLAYER

from async_worker import _resolve_single_activity
from dialogue_parser import Segment


class TestResolveSingleActivity:
    @pytest.mark.asyncio
    async def test_crafting_resolution(self):
        _conn, txn_p, get_p, claim_p, revert_p = patch_claim_stack(SAMPLE_ACTIVITY)
        with (
            txn_p,
            get_p,
            claim_p as mock_claim,
            revert_p as mock_revert,
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
            patch("async_worker.mark_resolved", new_callable=AsyncMock) as mock_mark,
            patch("async_worker.generate_notification_hook", new_callable=AsyncMock, return_value="Blade ready."),
            patch("async_worker.send_push_notification", new_callable=AsyncMock),
        ):
            await _resolve_single_activity(SAMPLE_ACTIVITY)

        mock_claim.assert_awaited_once()
        mock_revert.assert_not_awaited()
        # update_activity is the cache write only; mark_resolved is the terminal write.
        mock_update.assert_awaited_once()
        cache_call = mock_update.call_args_list[0]
        assert cache_call[0][0] == "activity_abc123"
        cached = cache_call[0][1]
        assert "outcome" in cached
        assert cached["narration_text"] == "The blade sings."
        assert cached["narration_summary"] == "Grimjaw is pleased with the blade."
        assert isinstance(cached["narration_segments"], list)
        assert cached["narration_segments"][0]["character"] == "GRIMJAW_BLACKSMITH"
        assert "decision_options" in cached
        # mark_resolved (not update_activity) writes the terminal state — strips resolving_at.
        mock_mark.assert_awaited_once()
        resolved_args = mock_mark.call_args[0]
        assert resolved_args[0] == "activity_abc123"
        resolved = resolved_args[1]
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

        _conn, txn_p, get_p, claim_p, revert_p = patch_claim_stack(activity)
        with (
            txn_p,
            get_p,
            claim_p,
            revert_p,
            patch("async_worker.db_queries.get_player", new_callable=AsyncMock, return_value=player_with_companion),
            patch(
                "errand_resolution.db_content_queries.get_location",
                new_callable=AsyncMock,
                return_value={"danger_level": 0},
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
            patch("async_worker.mark_resolved", new_callable=AsyncMock) as mock_mark,
            patch("async_worker.generate_notification_hook", new_callable=AsyncMock, return_value="Kael returns."),
            patch("async_worker.send_push_notification", new_callable=AsyncMock),
        ):
            await _resolve_single_activity(activity)

        # mark_resolved (not update_activity) writes the terminal state — strips resolving_at.
        mock_mark.assert_awaited_once()
        assert mock_mark.call_args[0][1]["status"] == "resolved"
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

        _conn, txn_p, get_p, claim_p, revert_p = patch_claim_stack(activity)
        with (
            txn_p,
            get_p,
            claim_p,
            revert_p,
            patch("async_worker.db_queries.get_player", new_callable=AsyncMock, return_value=player_with_companion),
            patch(
                "errand_resolution.db_content_queries.get_location",
                new_callable=AsyncMock,
                return_value={"danger_level": 2},
            ),
            patch("errand_risk.roll_errand_risk", MagicMock(return_value="injured")) as mock_roll,
            patch(
                "async_worker.generate_activity_narration",
                new_callable=AsyncMock,
                return_value=([Segment("COMPANION_KAEL", "neutral", "x")], "x", "x"),
            ),
            patch("async_worker.synthesize_segments", new_callable=AsyncMock, return_value="a.mp3"),
            patch("async_worker.db_mutations.update_activity", new_callable=AsyncMock) as mock_update,
            patch("async_worker.mark_resolved", new_callable=AsyncMock),
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

        _conn, txn_p, get_p, claim_p, revert_p = patch_claim_stack(activity)
        with (
            txn_p,
            get_p,
            claim_p,
            revert_p,
            patch("async_worker.db_queries.get_player", new_callable=AsyncMock, return_value=player_with_companion),
            patch("errand_resolution.db_content_queries.get_location", new_callable=AsyncMock, return_value=None),
            patch("errand_risk.roll_errand_risk", MagicMock(return_value="none")) as mock_roll,
            patch(
                "async_worker.generate_activity_narration",
                new_callable=AsyncMock,
                return_value=([Segment("COMPANION_KAEL", "neutral", "x")], "x", "x"),
            ),
            patch("async_worker.synthesize_segments", new_callable=AsyncMock, return_value="a.mp3"),
            patch("async_worker.db_mutations.update_activity", new_callable=AsyncMock),
            patch("async_worker.mark_resolved", new_callable=AsyncMock),
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
        """If narration fails, the activity is reverted resolving -> in_progress for retry."""
        _conn, txn_p, get_p, claim_p, revert_p = patch_claim_stack(SAMPLE_ACTIVITY)
        with (
            txn_p,
            get_p,
            claim_p,
            revert_p as mock_revert,
            patch("async_worker.db_queries.get_player", new_callable=AsyncMock, return_value=SAMPLE_PLAYER),
            patch(
                "async_worker.generate_activity_narration", new_callable=AsyncMock, side_effect=RuntimeError("LLM down")
            ),
            patch("async_worker.db_mutations.update_activity", new_callable=AsyncMock) as mock_update,
        ):
            with pytest.raises(RuntimeError):
                await _resolve_single_activity(SAMPLE_ACTIVITY)

        # No cache or resolved write — LLM blew up before either.
        mock_update.assert_not_awaited()
        # Claim must be reverted so the next tick retries.
        mock_revert.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_caches_narration_on_tts_failure(self):
        """If TTS fails, narration is cached, claim is reverted to in_progress."""
        _conn, txn_p, get_p, claim_p, revert_p = patch_claim_stack(SAMPLE_ACTIVITY)
        with (
            txn_p,
            get_p,
            claim_p,
            revert_p as mock_revert,
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
        # Claim is reverted so the next tick retries TTS with the cached narration.
        mock_revert.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handles_missing_player_data(self):
        """Should still work with empty player data."""
        _conn, txn_p, get_p, claim_p, revert_p = patch_claim_stack(SAMPLE_ACTIVITY)
        with (
            txn_p,
            get_p,
            claim_p,
            revert_p,
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
            patch("async_worker.mark_resolved", new_callable=AsyncMock) as mock_mark,
            patch("async_worker.generate_notification_hook", new_callable=AsyncMock, return_value="Update."),
            patch("async_worker.send_push_notification", new_callable=AsyncMock),
        ):
            await _resolve_single_activity(SAMPLE_ACTIVITY)

        # cache write via update_activity (1) + terminal write via mark_resolved (1)
        mock_update.assert_awaited_once()
        mock_mark.assert_awaited_once()
        assert mock_mark.call_args[0][1]["status"] == "resolved"

    @pytest.mark.asyncio
    async def test_skips_when_row_vanished_inside_lock(self):
        """Row deleted between get_due_activities and FOR-UPDATE lock — return cleanly,
        never attempt to claim, never run LLM/TTS, never revert.

        Covers the `if fresh is None: return` branch in _resolve_single_activity.
        """
        mock_conn = MagicMock()
        with (
            patch("async_worker.db.transaction", lambda: mock_txn(mock_conn)),
            patch(
                "async_worker.db_activity_queries.get_activity",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("async_worker.claim_resolving", new_callable=AsyncMock) as mock_claim,
            patch("async_worker.revert_claim_safe", new_callable=AsyncMock) as mock_revert,
            patch("async_worker.db_queries.get_player", new_callable=AsyncMock) as mock_player,
            patch("async_worker.generate_activity_narration", new_callable=AsyncMock) as mock_narration,
            patch("async_worker.synthesize_segments", new_callable=AsyncMock) as mock_tts,
            patch("async_worker.mark_resolved", new_callable=AsyncMock) as mock_mark,
        ):
            await _resolve_single_activity(SAMPLE_ACTIVITY)

        mock_claim.assert_not_awaited()
        mock_player.assert_not_awaited()
        mock_narration.assert_not_awaited()
        mock_tts.assert_not_awaited()
        mock_mark.assert_not_awaited()
        mock_revert.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cancelled_error_propagates_without_revert(self):
        """CancelledError during work phase (e.g. shutdown) must re-raise unhandled,
        not open a new revert txn that could hang during shutdown. The
        stale-resolving sweep on next boot recovers the row."""
        import asyncio

        _conn, txn_p, get_p, claim_p, revert_p = patch_claim_stack(SAMPLE_ACTIVITY)
        with (
            txn_p,
            get_p,
            claim_p,
            revert_p as mock_revert,
            patch("async_worker.db_queries.get_player", new_callable=AsyncMock, return_value=SAMPLE_PLAYER),
            patch(
                "async_worker.generate_activity_narration",
                new_callable=AsyncMock,
                side_effect=asyncio.CancelledError(),
            ),
        ):
            with pytest.raises(asyncio.CancelledError):
                await _resolve_single_activity(SAMPLE_ACTIVITY)

        mock_revert.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_when_already_resolving(self):
        """If another path already claimed (claim_resolving returns False),
        the worker logs and returns without calling LLM/TTS or updating."""
        _conn, txn_p, get_p, claim_p, revert_p = patch_claim_stack(SAMPLE_ACTIVITY, claim_returns=False)
        with (
            txn_p,
            get_p,
            claim_p,
            revert_p as mock_revert,
            patch("async_worker.db_queries.get_player", new_callable=AsyncMock) as mock_player,
            patch("async_worker.generate_activity_narration", new_callable=AsyncMock) as mock_narration,
            patch("async_worker.synthesize_segments", new_callable=AsyncMock) as mock_tts,
            patch("async_worker.db_mutations.update_activity", new_callable=AsyncMock) as mock_update,
        ):
            # Should return cleanly without raising.
            await _resolve_single_activity(SAMPLE_ACTIVITY)

        mock_player.assert_not_awaited()
        mock_narration.assert_not_awaited()
        mock_tts.assert_not_awaited()
        mock_update.assert_not_awaited()
        # Nothing to revert — we never owned the claim.
        mock_revert.assert_not_awaited()
