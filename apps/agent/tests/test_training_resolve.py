"""Tests for the resolve_training_midpoint agent tool (M1.5)."""

import json
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sample_fixtures import FIXED_NOW, make_context, make_db_mod

from training_rules import MidpointResult
from training_tools import _resolve_training_midpoint_impl

SAMPLE_AWAITING_ROW = {
    "id": "train_abc123",
    "player_id": "player_1",
    "activity_type": "technique_base",
    "state": "awaiting_decision",
    "data": {"first_half_seconds": 6 * 3600, "program_id": "combat_basics"},
}


def _make_midpoint_result(second_half_seconds: int = 5 * 3600, decision_id: str = "fundamentals"):
    return MidpointResult(
        state="running_second_half",
        second_half_seconds=second_half_seconds,
        completes_at=FIXED_NOW + timedelta(seconds=second_half_seconds),
        micro_bonus={"type": "fundamentals"},
        decision_id=decision_id,
    )


def _stub_resolve_factory(result: MidpointResult):
    def _stub(_activity_type, _decision_id, _decision_time):
        return result

    return _stub


def _stub_resolve_raises(msg: str):
    def _stub(_activity_type, _decision_id, _decision_time):
        raise ValueError(msg)

    return _stub


class TestResolveTrainingMidpoint:
    @pytest.mark.asyncio
    async def test_happy_path_advances_to_second_half(self):
        ctx = make_context()
        mock_db, mock_conn = make_db_mod()
        mock_training = MagicMock()
        mock_training.get_training_activity = AsyncMock(return_value=SAMPLE_AWAITING_ROW)
        mock_training.update_training_activity = AsyncMock()
        result = _make_midpoint_result()
        json_result = json.loads(
            await _resolve_training_midpoint_impl(
                ctx,
                "train_abc123",
                "fundamentals",
                db_mod=mock_db,
                db_training_mod=mock_training,
                rules_mod=_stub_resolve_factory(result),
                now_fn=lambda: FIXED_NOW,
            )
        )
        assert json_result["activity_id"] == "train_abc123"
        assert json_result["state"] == "running_second_half"
        assert json_result["second_half_seconds"] == 5 * 3600
        assert json_result["decision_id"] == "fundamentals"
        ctx.disallow_interruptions.assert_called_once()
        mock_training.get_training_activity.assert_awaited_once_with("train_abc123", conn=mock_conn, for_update=True)
        kwargs = mock_training.update_training_activity.await_args.kwargs
        assert mock_training.update_training_activity.await_args.args == ("train_abc123",)
        assert kwargs["state"] == "running_second_half"
        assert kwargs["data_updates"] == {
            "decision_id": "fundamentals",
            "second_half_seconds": 5 * 3600,
            "micro_bonus": {"type": "fundamentals"},
        }
        assert kwargs["conn"] is mock_conn

    @pytest.mark.asyncio
    async def test_invalid_training_id_format(self):
        ctx = make_context()
        mock_db, _ = make_db_mod()
        mock_training = MagicMock()
        mock_training.get_training_activity = AsyncMock()
        mock_training.update_training_activity = AsyncMock()
        result = json.loads(
            await _resolve_training_midpoint_impl(
                ctx,
                "bad id!! spaces",
                "fundamentals",
                db_mod=mock_db,
                db_training_mod=mock_training,
                now_fn=lambda: FIXED_NOW,
            )
        )
        assert result["code"] == "INVALID_TRAINING_ID"
        assert "training_id" in result["error"]
        mock_training.get_training_activity.assert_not_awaited()
        mock_training.update_training_activity.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_training_returns_error(self):
        ctx = make_context()
        mock_db, _ = make_db_mod()
        mock_training = MagicMock()
        mock_training.get_training_activity = AsyncMock(return_value=None)
        mock_training.update_training_activity = AsyncMock()
        result = json.loads(
            await _resolve_training_midpoint_impl(
                ctx,
                "train_missing",
                "fundamentals",
                db_mod=mock_db,
                db_training_mod=mock_training,
                now_fn=lambda: FIXED_NOW,
            )
        )
        assert result == {"error": "Unknown training: train_missing", "code": "UNKNOWN_TRAINING"}
        mock_training.update_training_activity.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_not_owned_returns_error(self):
        ctx = make_context(player_id="player_2")
        mock_db, _ = make_db_mod()
        mock_training = MagicMock()
        mock_training.get_training_activity = AsyncMock(return_value=SAMPLE_AWAITING_ROW)
        mock_training.update_training_activity = AsyncMock()
        result = json.loads(
            await _resolve_training_midpoint_impl(
                ctx,
                "train_abc123",
                "fundamentals",
                db_mod=mock_db,
                db_training_mod=mock_training,
                now_fn=lambda: FIXED_NOW,
            )
        )
        assert result["code"] == "TRAINING_NOT_OWNED"
        mock_training.update_training_activity.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_wrong_state_first_half(self):
        ctx = make_context()
        mock_db, _ = make_db_mod()
        mock_training = MagicMock()
        mock_training.get_training_activity = AsyncMock(
            return_value={**SAMPLE_AWAITING_ROW, "state": "running_first_half"}
        )
        mock_training.update_training_activity = AsyncMock()
        result = json.loads(
            await _resolve_training_midpoint_impl(
                ctx,
                "train_abc123",
                "fundamentals",
                db_mod=mock_db,
                db_training_mod=mock_training,
                now_fn=lambda: FIXED_NOW,
            )
        )
        assert result["code"] == "TRAINING_WRONG_STATE"
        assert "running_first_half" in result["error"]
        mock_training.update_training_activity.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_wrong_state_already_running_second(self):
        """Idempotency guard: re-resolving an already-resolved row is rejected."""
        ctx = make_context()
        mock_db, _ = make_db_mod()
        mock_training = MagicMock()
        mock_training.get_training_activity = AsyncMock(
            return_value={**SAMPLE_AWAITING_ROW, "state": "running_second_half"}
        )
        mock_training.update_training_activity = AsyncMock()
        result = json.loads(
            await _resolve_training_midpoint_impl(
                ctx,
                "train_abc123",
                "fundamentals",
                db_mod=mock_db,
                db_training_mod=mock_training,
                now_fn=lambda: FIXED_NOW,
            )
        )
        assert result["code"] == "TRAINING_WRONG_STATE"
        mock_training.update_training_activity.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_wrong_state_complete(self):
        ctx = make_context()
        mock_db, _ = make_db_mod()
        mock_training = MagicMock()
        mock_training.get_training_activity = AsyncMock(return_value={**SAMPLE_AWAITING_ROW, "state": "complete"})
        mock_training.update_training_activity = AsyncMock()
        result = json.loads(
            await _resolve_training_midpoint_impl(
                ctx,
                "train_abc123",
                "fundamentals",
                db_mod=mock_db,
                db_training_mod=mock_training,
                now_fn=lambda: FIXED_NOW,
            )
        )
        assert result["code"] == "TRAINING_WRONG_STATE"
        mock_training.update_training_activity.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_invalid_decision_returns_error(self):
        ctx = make_context()
        mock_db, _ = make_db_mod()
        mock_training = MagicMock()
        mock_training.get_training_activity = AsyncMock(return_value=SAMPLE_AWAITING_ROW)
        mock_training.update_training_activity = AsyncMock()
        result = json.loads(
            await _resolve_training_midpoint_impl(
                ctx,
                "train_abc123",
                "bogus_decision",
                db_mod=mock_db,
                db_training_mod=mock_training,
                rules_mod=_stub_resolve_raises(
                    "Invalid decision 'bogus_decision' for technique_base. Valid: ['fundamentals', 'advanced']"
                ),
                now_fn=lambda: FIXED_NOW,
            )
        )
        assert result["code"] == "INVALID_DECISION"
        assert "bogus_decision" in result["error"]
        mock_training.update_training_activity.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_writes_transition_at_matching_completes_at(self):
        """Regression guard: worker (advance_training_cycles) polls on
        transition_at; without it the resolved row stalls in
        running_second_half forever. Pins update_training_activity kwarg."""
        ctx = make_context()
        mock_db, _ = make_db_mod()
        mock_training = MagicMock()
        mock_training.get_training_activity = AsyncMock(return_value=SAMPLE_AWAITING_ROW)
        mock_training.update_training_activity = AsyncMock()
        result_data = _make_midpoint_result(second_half_seconds=4 * 3600)
        await _resolve_training_midpoint_impl(
            ctx,
            "train_abc123",
            "fundamentals",
            db_mod=mock_db,
            db_training_mod=mock_training,
            rules_mod=_stub_resolve_factory(result_data),
            now_fn=lambda: FIXED_NOW,
        )
        kwargs = mock_training.update_training_activity.await_args.kwargs
        assert kwargs["transition_at"] is not None
        assert kwargs["transition_at"] == FIXED_NOW + timedelta(seconds=4 * 3600)
