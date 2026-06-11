"""Regression tests for db_training create/update SQL + params.

Pins the transition_at handling that the async worker
(advance_training_cycles) depends on: a row without transition_at is
never polled, so both create and update must thread it through to the
right SQL branch. Both functions accept an injectable conn= so these
assert the SQL/params directly against a mock connection.
"""

import json
from unittest.mock import AsyncMock

import pytest
from sample_fixtures import FIXED_NOW

import db_training


def _mock_conn():
    conn = AsyncMock()
    conn.execute = AsyncMock()
    return conn


class TestCreateTrainingActivity:
    @pytest.mark.asyncio
    async def test_returns_prefixed_id_and_inserts(self):
        conn = _mock_conn()
        data = {"program_id": "combat_basics"}
        activity_id = await db_training.create_training_activity(
            "player_1", "technique_base", "running_first_half", data, conn=conn
        )
        assert activity_id.startswith("train_")
        sql, *args = conn.execute.await_args.args
        assert "INSERT INTO training_activities" in sql
        # Positional order: id, player_id, activity_type, state, data, transition_at
        assert args[0] == activity_id
        assert args[1] == "player_1"
        assert args[2] == "technique_base"
        assert args[3] == "running_first_half"
        assert args[4] == json.dumps(data)
        assert args[5] is None

    @pytest.mark.asyncio
    async def test_threads_transition_at_into_insert(self):
        conn = _mock_conn()
        await db_training.create_training_activity(
            "player_1", "technique_base", "running_first_half", {}, transition_at=FIXED_NOW, conn=conn
        )
        args = conn.execute.await_args.args
        assert args[6] == FIXED_NOW


class TestUpdateTrainingActivity:
    @pytest.mark.asyncio
    async def test_without_transition_at_omits_column(self):
        conn = _mock_conn()
        updates = {"decision_id": "fundamentals"}
        await db_training.update_training_activity("train_abc", "running_second_half", updates, conn=conn)
        sql, *args = conn.execute.await_args.args
        assert "UPDATE training_activities" in sql
        assert "transition_at" not in sql
        assert args == ["train_abc", "running_second_half", json.dumps(updates)]

    @pytest.mark.asyncio
    async def test_with_transition_at_sets_column(self):
        conn = _mock_conn()
        updates = {"decision_id": "fundamentals"}
        await db_training.update_training_activity(
            "train_abc", "running_second_half", updates, transition_at=FIXED_NOW, conn=conn
        )
        sql, *args = conn.execute.await_args.args
        assert "UPDATE training_activities" in sql
        assert "transition_at = $4" in sql
        assert args == ["train_abc", "running_second_half", json.dumps(updates), FIXED_NOW]


class TestUpsertLearningCycle:
    """The shared engine behind the spell + mentor-variant per-cycle upserts (concern
    5d7feeae22ae). table is whitelisted -> entity column; the two tracks differ only
    there. Pins the parametrization + guards directly against a mock connection."""

    def _row_conn(self, completed=1, required=3):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={"cycles_completed": completed, "cycles_required": required, "midpoint_decision_id": None}
        )
        return conn

    @pytest.mark.asyncio
    async def test_unknown_table_rejected(self):
        with pytest.raises(ValueError, match="unknown learning-progress table"):
            await db_training.upsert_learning_cycle("player_xp", "p1", "e1", 3, conn=self._row_conn())

    @pytest.mark.asyncio
    async def test_cycles_required_below_one_rejected(self):
        with pytest.raises(ValueError, match="cycles_required must be >= 1"):
            await db_training.upsert_learning_cycle(
                "spell_learning_progress", "p1", "fireball", 0, conn=self._row_conn()
            )

    @pytest.mark.asyncio
    async def test_spell_table_parametrization(self):
        conn = self._row_conn(completed=1, required=3)
        result = await db_training.upsert_learning_cycle(
            "spell_learning_progress", "p1", "fireball", 3, activity_id="train_a", conn=conn
        )
        sql, *params = conn.fetchrow.call_args.args
        assert "INSERT INTO spell_learning_progress" in sql
        assert "ON CONFLICT (player_id, spell_id) DO UPDATE" in sql
        assert "last_activity_id IS NOT DISTINCT FROM" in sql
        assert params == ["p1", "fireball", 3, None, "train_a"]
        assert result == {
            "cycles_completed": 1,
            "cycles_required": 3,
            "completed": False,
            "midpoint_decision_id": None,
        }

    @pytest.mark.asyncio
    async def test_variant_table_parametrization_and_completion(self):
        conn = self._row_conn(completed=3, required=3)
        result = await db_training.upsert_learning_cycle(
            "mentor_variant_learning_progress", "p1", "warrior_cleaving_blow_drathian", 3, conn=conn
        )
        sql, *params = conn.fetchrow.call_args.args
        assert "INSERT INTO mentor_variant_learning_progress" in sql
        assert "ON CONFLICT (player_id, variant_id) DO UPDATE" in sql
        assert params == ["p1", "warrior_cleaving_blow_drathian", 3, None, None]
        assert result["completed"] is True

    @pytest.mark.asyncio
    async def test_fail_loud_when_no_row_returned(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        with pytest.raises(RuntimeError, match="returned no row"):
            await db_training.upsert_learning_cycle("spell_learning_progress", "p1", "fireball", 3, conn=conn)
