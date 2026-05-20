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
