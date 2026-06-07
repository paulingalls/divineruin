"""Tests for the M9 mentor-variant persistence layer (mentor_variant_progress).

Pass a mock conn directly (the functions accept conn=) and assert the SQL +
params, mirroring test_character_spells.py. Real SQL is exercised against a
testcontainer at the story-004 capstone (ADR 0003).

character_mentor_variants is the unlocked set; mentor_variant_learning_progress is
the in-flight multi-session loop counted in discrete cycles. last_activity_id makes
cycle accrual idempotent under a worker retry (debt b20815f92023).
"""

from unittest.mock import AsyncMock

import pytest

import mentor_variant_progress as mvp


class TestSeedProgress:
    async def test_inserts_at_zero_idempotent(self):
        conn = AsyncMock()
        await mvp.seed_progress("p1", "warrior_cleaving_blow_drathian", 3, conn=conn)
        sql, *params = conn.execute.call_args.args
        assert "INSERT INTO mentor_variant_learning_progress" in sql
        assert "ON CONFLICT (player_id, variant_id) DO NOTHING" in sql
        # cycles_completed starts at 0 — learn(variant) seeds before any session completes.
        assert params == ["p1", "warrior_cleaving_blow_drathian", 3]


class TestAdvanceLearningCycle:
    async def test_increments_and_reports_incomplete(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={"cycles_completed": 1, "cycles_required": 3, "midpoint_decision_id": None}
        )
        result = await mvp.advance_learning_cycle(
            "p1", "warrior_cleaving_blow_drathian", 3, activity_id="train_a", conn=conn
        )
        sql, *params = conn.fetchrow.call_args.args
        assert "INSERT INTO mentor_variant_learning_progress" in sql
        assert "ON CONFLICT (player_id, variant_id) DO UPDATE" in sql
        # Idempotency: the increment is gated on a new activity id (debt b20815f92023).
        assert "last_activity_id IS NOT DISTINCT FROM" in sql
        assert "last_activity_id = $5" in sql
        assert params == ["p1", "warrior_cleaving_blow_drathian", 3, None, "train_a"]
        assert result == {
            "cycles_completed": 1,
            "cycles_required": 3,
            "completed": False,
            "midpoint_decision_id": None,
        }

    async def test_reports_completed_at_threshold(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={"cycles_completed": 3, "cycles_required": 3, "midpoint_decision_id": "speed"}
        )
        result = await mvp.advance_learning_cycle(
            "p1", "warrior_cleaving_blow_drathian", 3, activity_id="train_c", midpoint_decision_id="speed", conn=conn
        )
        assert result["completed"] is True
        assert result["midpoint_decision_id"] == "speed"

    @pytest.mark.parametrize("bad_required", [0, -1])
    async def test_rejects_non_positive_cycles_required(self, bad_required):
        conn = AsyncMock()
        with pytest.raises(ValueError, match="cycles_required"):
            await mvp.advance_learning_cycle("p1", "v1", bad_required, conn=conn)
        conn.fetchrow.assert_not_awaited()


class TestRecordUnlocked:
    async def test_inserts_unlocked_idempotent(self):
        conn = AsyncMock()
        await mvp.record_unlocked("p1", "warrior_cleaving_blow_drathian", midpoint_decision_id="speed", conn=conn)
        sql, *params = conn.execute.call_args.args
        assert "INSERT INTO character_mentor_variants" in sql
        assert "ON CONFLICT (player_id, variant_id) DO NOTHING" in sql
        # acquisition_track is always 'mentor_training' (the only track for variants).
        assert params == ["p1", "warrior_cleaving_blow_drathian", "mentor_training", "speed"]


class TestProgressHelpers:
    async def test_get_learning_progress_returns_row(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={"cycles_completed": 2, "cycles_required": 3, "midpoint_decision_id": None}
        )
        row = await mvp.get_learning_progress("p1", "warrior_cleaving_blow_drathian", conn=conn)
        sql, *params = conn.fetchrow.call_args.args
        assert "FROM mentor_variant_learning_progress WHERE player_id = $1 AND variant_id = $2" in sql
        assert params == ["p1", "warrior_cleaving_blow_drathian"]
        assert row == {"cycles_completed": 2, "cycles_required": 3, "midpoint_decision_id": None}

    async def test_get_learning_progress_none_when_absent(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        assert await mvp.get_learning_progress("p1", "v1", conn=conn) is None

    async def test_delete_learning_progress(self):
        conn = AsyncMock()
        await mvp.delete_learning_progress("p1", "warrior_cleaving_blow_drathian", conn=conn)
        sql, *params = conn.execute.call_args.args
        assert "DELETE FROM mentor_variant_learning_progress WHERE player_id = $1 AND variant_id = $2" in sql
        assert params == ["p1", "warrior_cleaving_blow_drathian"]

    async def test_is_unlocked_true_when_row_exists(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=True)
        result = await mvp.is_unlocked("p1", "warrior_cleaving_blow_drathian", conn=conn)
        sql, *params = conn.fetchval.call_args.args
        assert "SELECT EXISTS" in sql
        assert "FROM character_mentor_variants WHERE player_id = $1 AND variant_id = $2" in sql
        assert params == ["p1", "warrior_cleaving_blow_drathian"]
        assert result is True

    async def test_is_unlocked_false_when_absent(self):
        # An absent variant must report False, not a truthy non-bool — the False case
        # guards a regression where is_unlocked returns the wrong value for a variant
        # the player has not unlocked.
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=False)
        result = await mvp.is_unlocked("p1", "warrior_cleaving_blow_drathian", conn=conn)
        assert result is False


class TestGetUnlocked:
    async def test_selects_player_variant_set(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(
            return_value=[
                {
                    "variant_id": "warrior_cleaving_blow_drathian",
                    "acquisition_track": "mentor_training",
                    "midpoint_decision_id": "speed",
                },
            ]
        )
        rows = await mvp.get_unlocked("p1", conn=conn)
        sql, *params = conn.fetch.call_args.args
        assert "FROM character_mentor_variants WHERE player_id = $1" in sql
        assert params == ["p1"]
        assert rows == [
            {
                "variant_id": "warrior_cleaving_blow_drathian",
                "acquisition_track": "mentor_training",
                "midpoint_decision_id": "speed",
            }
        ]
