"""Spell-training cycle accrual + promotion (M8 story-004).

A completed spell-training activity = one cycle toward that spell's
spell_learning_progress. When the tier's cycle count is reached, the worker
promotes the spell into the known library (record_learned + clear progress).

Unit tests mock the persistence layer (AsyncMock) and drive the worker's
completion branch. TestSpellTrainingThreeCycleStandard exercises the full
3-cycles-to-known orchestration (AC4's behavior) with a stateful fake.

The literal real-Postgres single-DB assertion for AC4 rides the M8 story-007
capstone in tests/acceptance/ (ADR 0003: real-DB testcontainer fixtures live in
tests/acceptance/conftest.py, unreachable from tests/ — story-002/003 deferred
the same way; decision retro-try-ac4-capstone-placement).
"""

from unittest.mock import AsyncMock, patch

import pytest

from async_worker_training import advance_training_cycles
from dialogue_parser import Segment

SAMPLE_PLAYER = {"player_id": "player_1", "name": "Aldric"}

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


def _completion_patches(activity, *, advance_return):
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
        patch("async_worker_training.db_queries.get_player", new_callable=AsyncMock, return_value=SAMPLE_PLAYER),
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
            count = await advance_training_cycles()

        assert count == 1
        # One cycle accrued against this spell, sized by the major tier (5 cycles).
        advance.assert_awaited_once()
        assert advance.call_args.args[:2] == ("player_1", "arcane_fireball")
        assert advance.call_args.args[2] == 5  # cycles_required from content config
        # Promotion fired.
        record_learned.assert_awaited_once_with("player_1", "arcane_fireball", "training")
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
        else block, so advance_learning_cycle does NOT re-run. (This guards only the
        post-cache retry window; a narration failure before the cache write can still
        re-accrue — a pre-existing exposure shared with skill_practice, tracked as debt.)"""
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


class _FakeSpellStore:
    """Stateful stand-in for character_spells' progress + known tables.

    Lets a test drive the worker across multiple real completion cycles without a
    DB — the 3-cycles-to-known orchestration (AC4's behavior). The literal
    real-Postgres assertion rides the M8 story-007 capstone (see module docstring).
    """

    def __init__(self) -> None:
        self.progress: dict[tuple[str, str], int] = {}
        self.known: dict[tuple[str, str], str] = {}

    async def advance_learning_cycle(self, player_id, spell_id, cycles_required, **_kwargs):
        key = (player_id, spell_id)
        self.progress[key] = self.progress.get(key, 0) + 1
        completed = self.progress[key] >= cycles_required
        return {
            "cycles_completed": self.progress[key],
            "cycles_required": cycles_required,
            "completed": completed,
        }

    async def record_learned(self, player_id, spell_id, acquisition_track):
        self.known[(player_id, spell_id)] = acquisition_track

    async def delete_learning_progress(self, player_id, spell_id):
        self.progress.pop((player_id, spell_id), None)


# A Standard-tier spell carries cycles_required=3 (content config via conftest);
# spell_standard midpoint decision ids are power/control.
SAMPLE_STANDARD_ACTIVITY = {
    "id": "train_std1",
    "player_id": "player_1",
    "activity_type": "spell_standard",
    "state": "running_second_half",
    "data": {"spell_id": "arcane_frost_touch", "program_name": "Frost Study", "decision_id": "power"},
    "transition_at": "2026-01-01T00:00:00Z",
}


class TestSpellTrainingThreeCycleStandard:
    @pytest.mark.asyncio
    async def test_standard_spell_known_after_three_cycles_not_before(self):
        """A Standard spell (3 cycles): three completed training activities make it
        known with acquisition_track='training', and it is NOT known after only two.
        Exercises the worker's full accrual→promotion orchestration end to end."""
        store = _FakeSpellStore()
        key = ("player_1", "arcane_frost_touch")
        mock_segments = [Segment("NARRATOR", "calm", "Frost settles.")]

        for cycle in (1, 2, 3):
            with (
                patch(
                    "async_worker_training.db_training.get_due_training_transitions",
                    new_callable=AsyncMock,
                    return_value=[SAMPLE_STANDARD_ACTIVITY],
                ),
                patch("async_worker_training.db_training.update_training_activity", new_callable=AsyncMock),
                patch(
                    "async_worker_training.db_queries.get_player", new_callable=AsyncMock, return_value=SAMPLE_PLAYER
                ),
                patch("async_worker_training.character_spells.advance_learning_cycle", store.advance_learning_cycle),
                patch("async_worker_training.character_spells.record_learned", store.record_learned),
                patch(
                    "async_worker_training.character_spells.delete_learning_progress", store.delete_learning_progress
                ),
                patch(
                    "async_worker_training.generate_activity_narration",
                    new_callable=AsyncMock,
                    return_value=(mock_segments, "Frost settles.", "Spell study complete."),
                ),
                patch("async_worker_training.synthesize_segments", new_callable=AsyncMock, return_value="x.mp3"),
                patch("async_worker_training.generate_notification_hook", new_callable=AsyncMock, return_value="Done."),
                patch("async_worker_training.send_push_notification", new_callable=AsyncMock),
            ):
                await advance_training_cycles()

            if cycle < 3:
                assert key not in store.known, f"spell known too early (after cycle {cycle})"
            else:
                assert store.known[key] == "training"
                # Promotion clears the in-flight progress row.
                assert key not in store.progress
