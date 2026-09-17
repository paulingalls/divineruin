"""Spell-training cycle accrual + promotion (M8 story-004).

A completed spell-training activity = one cycle toward that spell's
spell_learning_progress. When the tier's cycle count is reached, the worker
promotes the spell into the known library (record_learned + clear progress).

Unit tests isolate worker retry and promotion seams. The three-cycle diagnostic
uses the real begin_activity producer, Postgres rows, progress, and known library.
"""

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sample_fixtures import make_context

import character_spells
import db_training
from activity_payloads import Training, to_impl_kwargs
from activity_tools import _begin_activity_impl
from async_worker_training import advance_training_cycles
from dialogue_parser import Segment

SAMPLE_PLAYER = {"player_id": "player_1", "name": "Aldric", "class": "mage", "level": 5}

# A spell-training activity at the completion edge. spell_major carries
# cycles_required=5 (content config, loaded by the autouse conftest fixture);
# its midpoint decision ids are push/work_around.
SAMPLE_SPELL_ACTIVITY = {
    "id": "train_spell1",
    "player_id": "player_1",
    "activity_type": "spell_major",
    "state": "running_second_half",
    "data": {
        "spell_id": "arcane_fireball",
        "program_name": "Fireball Study",
        "decision_id": "push",
    },
    "transition_at": "2026-01-01T00:00:00Z",
}


def _completion_patches(activity, *, advance_return, player=SAMPLE_PLAYER):
    """Patch the worker's persistence + narration/TTS/push collaborators.

    Returns the patch context managers as a tuple plus the three character_spells
    mocks so a test can assert on them.
    """
    mock_segments = [Segment("NARRATOR", "awed", "The fire answers.")]
    advance = AsyncMock(return_value=advance_return)
    record_learned = AsyncMock()
    delete_progress = AsyncMock()
    patches = (
        patch(
            "async_worker_training.db_training.get_due_training_transitions",
            new_callable=AsyncMock,
            return_value=[activity],
        ),
        patch("async_worker_training.db_training.update_training_activity", new_callable=AsyncMock),
        patch("async_worker_training.db_queries.get_player", new_callable=AsyncMock, return_value=player),
        patch("async_worker_training.character_spells.advance_learning_cycle", advance),
        patch("async_worker_training.character_spells.record_learned", record_learned),
        patch("async_worker_training.character_spells.delete_learning_progress", delete_progress),
        patch(
            "async_worker_training.generate_activity_narration",
            new_callable=AsyncMock,
            return_value=(mock_segments, "The fire answers.", "Spell study complete."),
        ),
        patch("async_worker_training.synthesize_segments", new_callable=AsyncMock, return_value="train_spell1.mp3"),
        patch("async_worker_training.generate_notification_hook", new_callable=AsyncMock, return_value="Done."),
        patch("async_worker_training.send_push_notification", new_callable=AsyncMock),
    )
    return patches, advance, record_learned, delete_progress


class TestSpellTrainingAccrual:
    @pytest.mark.asyncio
    async def test_completed_cycle_promotes_spell_to_known_library(self):
        """When advance_learning_cycle reports completed, the spell is recorded learned
        with track='training' and its in-flight progress row is cleared (promotion seam)."""
        patches, advance, record_learned, delete_progress = _completion_patches(
            SAMPLE_SPELL_ACTIVITY,
            advance_return={
                "cycles_completed": 5,
                "cycles_required": 5,
                "completed": True,
                "midpoint_decision_id": "push",
            },
        )
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patches[6],
            patches[7],
            patches[8],
            patches[9],
        ):
            count = await advance_training_cycles()

        assert count == 1
        # One cycle accrued against this spell, sized by the major tier (5 cycles).
        advance.assert_awaited_once()
        assert advance.call_args.args[:2] == ("player_1", "arcane_fireball")
        assert advance.call_args.args[2] == 5  # cycles_required from content config
        # Promotion fired, carrying the recorded midpoint decision as the spell's
        # bonus_variant (AC3: the learned spell reflects the training decision).
        record_learned.assert_awaited_once_with("player_1", "arcane_fireball", "training", bonus_variant="push")
        delete_progress.assert_awaited_once_with("player_1", "arcane_fireball")

    @pytest.mark.asyncio
    async def test_incomplete_cycle_does_not_promote(self):
        """A cycle that does not complete the tier accrues but never promotes —
        no record_learned, no progress deletion (guards the strand-a-spell risk)."""
        patches, advance, record_learned, delete_progress = _completion_patches(
            SAMPLE_SPELL_ACTIVITY,
            advance_return={"cycles_completed": 4, "cycles_required": 5, "completed": False},
        )
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patches[6],
            patches[7],
            patches[8],
            patches[9],
        ):
            count = await advance_training_cycles()

        assert count == 1
        advance.assert_awaited_once()
        record_learned.assert_not_awaited()
        delete_progress.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_completed_cycle_refuses_off_source_promotion(self):
        patches, _, record_learned, _ = _completion_patches(
            SAMPLE_SPELL_ACTIVITY,
            player={"player_id": "player_1", "name": "Celia", "class": "cleric"},
            advance_return={
                "cycles_completed": 5,
                "cycles_required": 5,
                "completed": True,
                "midpoint_decision_id": "push",
            },
        )
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patches[6],
            patches[7],
            patches[8],
            patches[9],
        ):
            count = await advance_training_cycles()

        assert count == 0
        record_learned.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_completed_cycle_refuses_tier_locked_promotion(self):
        patches, _, record_learned, _ = _completion_patches(
            SAMPLE_SPELL_ACTIVITY,
            player={"player_id": "player_1", "name": "Aldric", "class": "mage", "level": 4},
            advance_return={
                "cycles_completed": 5,
                "cycles_required": 5,
                "completed": True,
                "midpoint_decision_id": "push",
            },
        )
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patches[6],
            patches[7],
            patches[8],
            patches[9],
        ):
            count = await advance_training_cycles()

        assert count == 0
        record_learned.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_midpoint_decision_threaded_to_progress(self):
        """The recorded midpoint decision (data['decision_id']) is passed through to
        advance_learning_cycle so the learned spell's bonus variant derives from it."""
        patches, advance, _, _ = _completion_patches(
            SAMPLE_SPELL_ACTIVITY,
            advance_return={"cycles_completed": 1, "cycles_required": 5, "completed": False},
        )
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patches[6],
            patches[7],
            patches[8],
            patches[9],
        ):
            await advance_training_cycles()

        assert advance.call_args.kwargs["midpoint_decision_id"] == "push"

    @pytest.mark.asyncio
    async def test_missing_spell_id_fails_loud(self):
        """A spell-training activity without spell_id in its data is a contract
        violation — the cycle is not silently dropped or promoted."""
        activity = {
            **SAMPLE_SPELL_ACTIVITY,
            "data": {k: v for k, v in SAMPLE_SPELL_ACTIVITY["data"].items() if k != "spell_id"},
        }
        patches, advance, record_learned, _ = _completion_patches(
            activity,
            advance_return={"cycles_completed": 1, "cycles_required": 5, "completed": False},
        )
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patches[6],
            patches[7],
            patches[8],
            patches[9],
        ):
            # The worker catches per-activity exceptions and retries next cycle, so it
            # returns 0 transitions rather than raising; accrual never runs.
            count = await advance_training_cycles()

        assert count == 0
        advance.assert_not_awaited()
        record_learned.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cached_narration_does_not_re_accrue(self):
        """On a TTS retry the worker reuses cached narration and skips the non-cached
        else block, so advance_learning_cycle does NOT re-run. A narration failure
        BEFORE the cache write re-enters this block but is now safe: the progress row
        is still present (delete is deferred until after the cache write), so advance
        re-runs as a no-op via last_activity_id rather than re-INSERTing a phantom row —
        see test_narration_failure_preserves_progress (debt b20815f92023, resolved)."""
        cached_activity = {
            **SAMPLE_SPELL_ACTIVITY,
            "data": {
                **SAMPLE_SPELL_ACTIVITY["data"],
                "narration_text": "The fire answers.",
                "narration_segments": [{"character": "NARRATOR", "emotion": "awed", "text": "The fire answers."}],
            },
        }
        patches, advance, record_learned, delete_progress = _completion_patches(
            cached_activity,
            advance_return={"cycles_completed": 5, "cycles_required": 5, "completed": True},
        )
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patches[6],
            patches[7],
            patches[8],
            patches[9],
        ):
            await advance_training_cycles()

        advance.assert_not_awaited()
        record_learned.assert_not_awaited()
        delete_progress.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_narration_failure_preserves_progress(self):
        """A completed spell whose narration fails must NOT delete the progress row.

        delete_learning_progress is deferred until after the narration is cached. If it
        ran before narration, a narration-failure retry would find no progress row and
        advance_learning_cycle would re-INSERT a phantom 1/5 row for the already-learned
        spell (the last_activity_id guard can only protect a row that still exists) —
        debt b20815f92023. record_learned still runs pre-narration (ON CONFLICT DO
        NOTHING makes it idempotent); only the delete must wait."""
        advance = AsyncMock(
            return_value={
                "cycles_completed": 5,
                "cycles_required": 5,
                "completed": True,
                "midpoint_decision_id": "push",
            }
        )
        record_learned = AsyncMock()
        delete_progress = AsyncMock()
        with (
            patch(
                "async_worker_training.db_training.get_due_training_transitions",
                new_callable=AsyncMock,
                return_value=[SAMPLE_SPELL_ACTIVITY],
            ),
            patch("async_worker_training.db_training.update_training_activity", new_callable=AsyncMock) as mock_update,
            patch("async_worker_training.db_queries.get_player", new_callable=AsyncMock, return_value=SAMPLE_PLAYER),
            patch("async_worker_training.character_spells.advance_learning_cycle", advance),
            patch("async_worker_training.character_spells.record_learned", record_learned),
            patch("async_worker_training.character_spells.delete_learning_progress", delete_progress),
            patch(
                "async_worker_training.generate_activity_narration",
                new_callable=AsyncMock,
                side_effect=RuntimeError("LLM down"),
            ),
        ):
            count = await advance_training_cycles()

        # Narration failed: no transition, no cache write, progress row preserved.
        assert count == 0
        mock_update.assert_not_awaited()
        delete_progress.assert_not_awaited()
        record_learned.assert_awaited_once()


class TestSpellTrainingThreeCycleStandard:
    @pytest.mark.asyncio
    async def test_real_producer_spell_known_after_three_cycles_not_before(self, dev_db_pool):
        player_id = f"test_player_{uuid.uuid4().hex}"
        spell_id = "arcane_hold_person"
        await dev_db_pool.execute(
            "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb)",
            player_id,
            json.dumps({"player_id": player_id, "name": "Mira", "class": "mage", "level": 3}),
        )
        real_due = db_training.get_due_training_transitions

        async def due_for_test_player():
            return [row for row in await real_due() if row["player_id"] == player_id]

        try:
            for cycle in (1, 2, 3):
                payload = Training(kind="training", program_id="arcane_study", spell_id=spell_id)
                kind, kwargs = to_impl_kwargs(payload)
                created = json.loads(await _begin_activity_impl(make_context(player_id=player_id), kind, **kwargs))
                activity_id = created["activity_id"]
                row = await db_training.get_training_activity(activity_id, conn=dev_db_pool)
                assert row is not None
                assert row["data"]["spell_id"] == spell_id

                await dev_db_pool.execute(
                    """
                    UPDATE training_activities
                    SET state = 'running_second_half',
                        data = data || '{"decision_id":"power"}'::jsonb,
                        transition_at = NOW() - INTERVAL '1 second'
                    WHERE id = $1
                    """,
                    activity_id,
                )
                segments = [Segment("NARRATOR", "calm", "The bindings settle.")]
                with (
                    patch(
                        "async_worker_training.db_training.get_due_training_transitions",
                        side_effect=due_for_test_player,
                    ),
                    patch(
                        "async_worker_training.generate_activity_narration",
                        new_callable=AsyncMock,
                        return_value=(segments, "The bindings settle.", "Spell study complete."),
                    ),
                    patch("async_worker_training.synthesize_segments", new_callable=AsyncMock),
                    patch(
                        "async_worker_training.generate_notification_hook",
                        new_callable=AsyncMock,
                        return_value="Done.",
                    ),
                    patch("async_worker_training.send_push_notification", new_callable=AsyncMock),
                ):
                    assert await advance_training_cycles() == 1

                known = {row["spell_id"]: row for row in await character_spells.get_known(player_id, conn=dev_db_pool)}
                if cycle < 3:
                    assert spell_id not in known
                else:
                    assert known[spell_id]["acquisition_track"] == "training"
                    assert known[spell_id]["bonus_variant"] == "power"
                    assert await character_spells.get_learning_progress(player_id, spell_id, conn=dev_db_pool) is None
        finally:
            await dev_db_pool.execute("DELETE FROM training_activities WHERE player_id = $1", player_id)
            await dev_db_pool.execute("DELETE FROM players WHERE player_id = $1", player_id)
