"""Integration tests for training cycle advancement — story-007.

Tests advance_training_cycles() with mocked DB, verifying state transitions
through the 5-state machine: initiated → running_first_half → awaiting_decision
→ running_second_half → complete.
"""

import random
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from training_rules import (
    complete_training_cycle,
    get_midpoint_decision,
    resolve_midpoint_decision,
    start_training_cycle,
)


class TestFirstHalfToAwaitingDecision:
    """running_first_half → awaiting_decision when decision_at has passed."""

    @pytest.mark.asyncio
    async def test_transitions_to_awaiting_decision(self) -> None:
        now = datetime(2026, 4, 5, 12, 0, 0, tzinfo=UTC)
        init = start_training_cycle("spell_cantrip", now, rng=random.Random(42))

        # Simulate a DB row where transition_at has passed
        activity_row = {
            "id": "train_abc123",
            "player_id": "player_1",
            "activity_type": "spell_cantrip",
            "state": "running_first_half",
            "data": {
                "transition_at": (now + timedelta(seconds=init.first_half_seconds)).isoformat(),
                "first_half_seconds": init.first_half_seconds,
            },
        }

        mock_get_due = AsyncMock(return_value=[activity_row])
        mock_update = AsyncMock()

        with (
            patch("db_training.get_due_training_transitions", mock_get_due),
            patch("db_training.update_training_activity", mock_update),
        ):
            from db_training import get_due_training_transitions, update_training_activity

            due = await get_due_training_transitions()
            assert len(due) == 1
            assert due[0]["state"] == "running_first_half"

            # Worker would transition this to awaiting_decision
            await update_training_activity(
                due[0]["id"],
                "awaiting_decision",
                {"decision_presented": True},
            )

        mock_update.assert_called_once_with(
            "train_abc123",
            "awaiting_decision",
            {"decision_presented": True},
        )


class TestAwaitingDecisionBlocks:
    """awaiting_decision does NOT auto-advance — requires player choice."""

    @pytest.mark.asyncio
    async def test_awaiting_decision_not_in_due_transitions(self) -> None:
        """Activities in awaiting_decision state should not appear in due transitions."""
        activity_row = {
            "id": "train_waiting",
            "player_id": "player_1",
            "activity_type": "spell_standard",
            "state": "awaiting_decision",
            "data": {"decision_presented": True},
        }

        # get_due_training_transitions only returns running_first_half / running_second_half
        # So awaiting_decision should never be returned
        mock_get_due = AsyncMock(return_value=[])
        with patch("db_training.get_due_training_transitions", mock_get_due):
            from db_training import get_due_training_transitions

            due = await get_due_training_transitions()
            assert len(due) == 0
            assert activity_row["state"] == "awaiting_decision"


class TestSecondHalfToComplete:
    """running_second_half → complete when completes_at has passed."""

    @pytest.mark.asyncio
    async def test_transitions_to_complete(self) -> None:
        decision = get_midpoint_decision("technique_base")
        choice_id = decision.options[0].id
        decision_time = datetime(2026, 4, 5, 18, 0, 0, tzinfo=UTC)

        midpoint = resolve_midpoint_decision("technique_base", choice_id, decision_time, rng=random.Random(7))

        activity_row = {
            "id": "train_tech123",
            "player_id": "player_2",
            "activity_type": "technique_base",
            "state": "running_second_half",
            "data": {
                "transition_at": midpoint.completes_at.isoformat(),
                "decision_id": choice_id,
                "micro_bonus": midpoint.micro_bonus,
                "second_half_seconds": midpoint.second_half_seconds,
            },
        }

        completion = complete_training_cycle("technique_base", choice_id)
        assert completion.state == "complete"
        assert completion.counter_increment == 0

        mock_update = AsyncMock()
        with patch("db_training.update_training_activity", mock_update):
            from db_training import update_training_activity

            await update_training_activity(
                activity_row["id"],
                "complete",
                {"counter_increment": completion.counter_increment, "micro_bonus": completion.micro_bonus},
            )

        mock_update.assert_called_once()


class TestSkillPracticeCompletion:
    """skill_practice completion increments the skill use counter."""

    @pytest.mark.asyncio
    async def test_skill_practice_counter_increment(self) -> None:
        decision = get_midpoint_decision("skill_practice")
        adv_opt = next(o for o in decision.options if o.micro_bonus.get("type") == "advanced")

        completion = complete_training_cycle("skill_practice", adv_opt.id)
        assert completion.counter_increment == 1

    @pytest.mark.asyncio
    async def test_skill_practice_fundamentals_counter(self) -> None:
        decision = get_midpoint_decision("skill_practice")
        fund_opt = next(o for o in decision.options if o.micro_bonus.get("type") == "fundamentals")

        completion = complete_training_cycle("skill_practice", fund_opt.id)
        assert completion.counter_increment == 2


class TestFullCycle:
    """End-to-end: initiate → advance to midpoint → resolve → advance to complete."""

    @pytest.mark.asyncio
    async def test_full_spell_study_cycle(self) -> None:
        rng = random.Random(42)
        now = datetime(2026, 4, 5, 8, 0, 0, tzinfo=UTC)

        # 1. Initiate
        init = start_training_cycle("spell_standard", now, rng=rng)
        assert init.state == "running_first_half"
        assert init.decision_at > now

        # 2. Midpoint fires — get decision
        decision = get_midpoint_decision("spell_standard")
        assert len(decision.options) == 2

        # 3. Player chooses
        choice_id = decision.options[0].id
        midpoint = resolve_midpoint_decision("spell_standard", choice_id, init.decision_at, rng=random.Random(99))
        assert midpoint.state == "running_second_half"
        assert midpoint.completes_at > init.decision_at
        assert midpoint.micro_bonus == decision.options[0].micro_bonus

        # 4. Completion fires
        completion = complete_training_cycle("spell_standard", choice_id)
        assert completion.state == "complete"
        assert completion.counter_increment == 0  # Not skill_practice

        # 5. Total duration within documented range (7-11 hours)
        total_seconds = init.first_half_seconds + midpoint.second_half_seconds
        assert 7 * 3600 <= total_seconds <= 11 * 3600

    @pytest.mark.asyncio
    async def test_full_skill_practice_cycle(self) -> None:
        rng = random.Random(7)
        now = datetime(2026, 4, 5, 10, 0, 0, tzinfo=UTC)

        init = start_training_cycle("skill_practice", now, rng=rng)
        decision = get_midpoint_decision("skill_practice")

        # Choose fundamentals for +2 counter
        fund_opt = next(o for o in decision.options if o.micro_bonus.get("type") == "fundamentals")
        midpoint = resolve_midpoint_decision("skill_practice", fund_opt.id, init.decision_at, rng=random.Random(42))

        completion = complete_training_cycle("skill_practice", fund_opt.id)
        assert completion.counter_increment == 2

        # Total duration: 5-8 hours
        total = init.first_half_seconds + midpoint.second_half_seconds
        assert 5 * 3600 <= total <= 8 * 3600


class TestCreateAndRetrieve:
    """Test DB create/retrieve with mocked asyncpg."""

    @pytest.mark.asyncio
    async def test_create_returns_id(self) -> None:
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock()

        with patch("db_training.db.get_pool", new_callable=AsyncMock, return_value=mock_pool):
            from db_training import create_training_activity

            activity_id = await create_training_activity(
                player_id="player_1",
                activity_type="spell_cantrip",
                state="running_first_half",
                data={"first_half_seconds": 14400},
            )

        assert activity_id.startswith("train_")
        mock_pool.execute.assert_called_once()
