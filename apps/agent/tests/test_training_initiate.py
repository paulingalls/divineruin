"""Tests for query_training_programs + initiate_training_cycle agent tools (M1.5)."""

import json
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sample_fixtures import FIXED_NOW, make_context, make_db_mod

from training_rules import TrainingCycleInit
from training_tools import _initiate_training_cycle_impl, _query_training_programs_impl

SAMPLE_PROGRAM = {
    "id": "combat_basics",
    "name": "Combat Fundamentals",
    "training_activity_type": "technique_base",
    "stat": "strength",
    "dc": 13,
    "mentor_id": "guildmaster_torin",
}

SAMPLE_PROGRAM_WITH_SKILL = {
    "id": "lore_basics",
    "name": "Lore Foundations",
    "training_activity_type": "skill_practice",
    "stat": "intelligence",
    "skill": "arcana",
    "dc": 12,
    "mentor_id": "archivist_lyra",
}


def _make_cycle(first_half_seconds: int = 6 * 3600) -> TrainingCycleInit:
    return TrainingCycleInit(
        state="running_first_half",
        first_half_seconds=first_half_seconds,
        decision_at=FIXED_NOW + timedelta(seconds=first_half_seconds),
    )


def _stub_rules_factory(cycle: TrainingCycleInit):
    def _stub(_activity_type, _start_time):
        return cycle

    return _stub


def _stub_rules_raises():
    def _stub(activity_type, _start_time):
        raise ValueError(f"Unknown training activity type: {activity_type!r}")

    return _stub


class TestQueryTrainingPrograms:
    @pytest.mark.asyncio
    async def test_returns_program_list(self):
        ctx = make_context()
        mock_content = MagicMock()
        mock_content.list_training_programs = AsyncMock(return_value=[SAMPLE_PROGRAM, SAMPLE_PROGRAM_WITH_SKILL])
        result = json.loads(await _query_training_programs_impl(ctx, db_content_mod=mock_content))
        assert result == {"programs": [SAMPLE_PROGRAM, SAMPLE_PROGRAM_WITH_SKILL]}
        mock_content.list_training_programs.assert_awaited_once()


class TestInitiateTrainingCycle:
    @pytest.mark.asyncio
    async def test_happy_path_creates_row(self):
        ctx = make_context()
        mock_db, mock_conn = make_db_mod()
        mock_content = MagicMock()
        mock_content.get_training_program = AsyncMock(return_value=SAMPLE_PROGRAM)
        mock_training = MagicMock()
        mock_training.get_player_training_activities = AsyncMock(return_value=[])
        mock_training.create_training_activity = AsyncMock(return_value="train_abc123")
        cycle = _make_cycle(first_half_seconds=8 * 3600)
        result = json.loads(
            await _initiate_training_cycle_impl(
                ctx,
                "combat_basics",
                db_mod=mock_db,
                db_training_mod=mock_training,
                db_content_mod=mock_content,
                rules_mod=_stub_rules_factory(cycle),
                now_fn=lambda: FIXED_NOW,
            )
        )
        assert result["activity_id"] == "train_abc123"
        assert result["state"] == "running_first_half"
        assert result["first_half_seconds"] == 8 * 3600
        assert result["program_name"] == "Combat Fundamentals"
        ctx.disallow_interruptions.assert_called_once()
        kwargs = mock_training.create_training_activity.await_args.kwargs
        assert kwargs["player_id"] == "player_1"
        assert kwargs["activity_type"] == "technique_base"
        assert kwargs["state"] == "running_first_half"
        assert kwargs["conn"] is mock_conn
        assert kwargs["data"] == {
            "program_id": "combat_basics",
            "program_name": "Combat Fundamentals",
            "first_half_seconds": 8 * 3600,
            "stat": "strength",
            "skill": None,
            "dc": 13,
            "mentor_id": "guildmaster_torin",
        }

    @pytest.mark.asyncio
    async def test_program_with_skill_passes_through(self):
        ctx = make_context()
        mock_db, _ = make_db_mod()
        mock_content = MagicMock()
        mock_content.get_training_program = AsyncMock(return_value=SAMPLE_PROGRAM_WITH_SKILL)
        mock_training = MagicMock()
        mock_training.get_player_training_activities = AsyncMock(return_value=[])
        mock_training.create_training_activity = AsyncMock(return_value="train_skill")
        cycle = _make_cycle()
        await _initiate_training_cycle_impl(
            ctx,
            "lore_basics",
            db_mod=mock_db,
            db_training_mod=mock_training,
            db_content_mod=mock_content,
            rules_mod=_stub_rules_factory(cycle),
            now_fn=lambda: FIXED_NOW,
        )
        kwargs = mock_training.create_training_activity.await_args.kwargs
        assert kwargs["data"]["skill"] == "arcana"

    @pytest.mark.asyncio
    async def test_invalid_program_id_format_returns_error(self):
        """Pin _validate_id call — codebase convention is to reject malformed ids
        before any DB lookup so a bad call never touches the pool."""
        ctx = make_context()
        mock_db, _ = make_db_mod()
        mock_content = MagicMock()
        mock_content.get_training_program = AsyncMock()
        mock_training = MagicMock()
        mock_training.create_training_activity = AsyncMock()
        result = json.loads(
            await _initiate_training_cycle_impl(
                ctx,
                "bad id!! has spaces",
                db_mod=mock_db,
                db_training_mod=mock_training,
                db_content_mod=mock_content,
                now_fn=lambda: FIXED_NOW,
            )
        )
        assert result["code"] == "INVALID_PROGRAM_ID"
        assert "program_id" in result["error"]
        mock_content.get_training_program.assert_not_awaited()
        mock_training.create_training_activity.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_program_returns_error(self):
        ctx = make_context()
        mock_db, _ = make_db_mod()
        mock_content = MagicMock()
        mock_content.get_training_program = AsyncMock(return_value=None)
        mock_training = MagicMock()
        mock_training.create_training_activity = AsyncMock()
        result = json.loads(
            await _initiate_training_cycle_impl(
                ctx,
                "nonexistent",
                db_mod=mock_db,
                db_training_mod=mock_training,
                db_content_mod=mock_content,
                now_fn=lambda: FIXED_NOW,
            )
        )
        assert result == {"error": "Unknown training program: nonexistent", "code": "UNKNOWN_PROGRAM"}
        mock_training.create_training_activity.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_slot_conflict_blocks_when_non_complete_row_exists(self):
        ctx = make_context()
        mock_db, mock_conn = make_db_mod()
        mock_content = MagicMock()
        mock_content.get_training_program = AsyncMock(return_value=SAMPLE_PROGRAM)
        mock_training = MagicMock()
        mock_training.get_player_training_activities = AsyncMock(
            return_value=[{"id": "train_existing", "state": "running_first_half"}]
        )
        mock_training.create_training_activity = AsyncMock()
        cycle = _make_cycle()
        result = json.loads(
            await _initiate_training_cycle_impl(
                ctx,
                "combat_basics",
                db_mod=mock_db,
                db_training_mod=mock_training,
                db_content_mod=mock_content,
                rules_mod=_stub_rules_factory(cycle),
                now_fn=lambda: FIXED_NOW,
            )
        )
        assert result == {"error": "A training cycle is already in progress.", "code": "TRAINING_SLOT_FULL"}
        mock_training.get_player_training_activities.assert_awaited_once_with("player_1", state=None, conn=mock_conn)
        mock_training.create_training_activity.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_completed_row_does_not_block(self):
        ctx = make_context()
        mock_db, _ = make_db_mod()
        mock_content = MagicMock()
        mock_content.get_training_program = AsyncMock(return_value=SAMPLE_PROGRAM)
        mock_training = MagicMock()
        mock_training.get_player_training_activities = AsyncMock(
            return_value=[{"id": "train_done", "state": "complete"}]
        )
        mock_training.create_training_activity = AsyncMock(return_value="train_new")
        cycle = _make_cycle()
        result = json.loads(
            await _initiate_training_cycle_impl(
                ctx,
                "combat_basics",
                db_mod=mock_db,
                db_training_mod=mock_training,
                db_content_mod=mock_content,
                rules_mod=_stub_rules_factory(cycle),
                now_fn=lambda: FIXED_NOW,
            )
        )
        assert result["activity_id"] == "train_new"
        mock_training.create_training_activity.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unknown_activity_type_returns_error(self):
        ctx = make_context()
        mock_db, _ = make_db_mod()
        mock_content = MagicMock()
        mock_content.get_training_program = AsyncMock(
            return_value={**SAMPLE_PROGRAM, "training_activity_type": "totally_bogus"}
        )
        mock_training = MagicMock()
        mock_training.create_training_activity = AsyncMock()
        result = json.loads(
            await _initiate_training_cycle_impl(
                ctx,
                "combat_basics",
                db_mod=mock_db,
                db_training_mod=mock_training,
                db_content_mod=mock_content,
                rules_mod=_stub_rules_raises(),
                now_fn=lambda: FIXED_NOW,
            )
        )
        assert result["code"] == "UNKNOWN_ACTIVITY_TYPE"
        assert "totally_bogus" in result["error"]
        mock_training.create_training_activity.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_writes_transition_at_matching_decision_at(self):
        """Regression guard: tool must populate transition_at or the worker
        (async_worker.advance_training_cycles) never picks the row up.
        Pins the db_training.create_training_activity signature extension."""
        ctx = make_context()
        mock_db, _ = make_db_mod()
        mock_content = MagicMock()
        mock_content.get_training_program = AsyncMock(return_value=SAMPLE_PROGRAM)
        mock_training = MagicMock()
        mock_training.get_player_training_activities = AsyncMock(return_value=[])
        mock_training.create_training_activity = AsyncMock(return_value="train_xyz")
        cycle = _make_cycle(first_half_seconds=5 * 3600)
        await _initiate_training_cycle_impl(
            ctx,
            "combat_basics",
            db_mod=mock_db,
            db_training_mod=mock_training,
            db_content_mod=mock_content,
            rules_mod=_stub_rules_factory(cycle),
            now_fn=lambda: FIXED_NOW,
        )
        kwargs = mock_training.create_training_activity.await_args.kwargs
        assert kwargs["transition_at"] is not None
        assert kwargs["transition_at"] == FIXED_NOW + timedelta(seconds=5 * 3600)


# Training-tool registration moved to TrainingAgent in story-011 (CityAgent
# decomposition). The wiring is now pinned by tests/test_training_agent.py
# (TestTrainingAgentRegistration + TestCityToolBudget).
