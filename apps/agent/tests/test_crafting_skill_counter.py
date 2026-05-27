"""Hidden Crafting skill counter (+1 on Failure) — story-006.

Decision crafting-hidden-skill-counter (story-001) ships the spec's failure
consolation reward (game_mechanics_crafting.md:106): every crafting Failure grants
+1 toward a per-player hidden Crafting skill counter. The increment is a DB
mutation on the worker's outcome-application path — distinct from story-003's pure
resolver.

These are unit tests:
 - the async-worker hook fires increment exactly once on a 'failure'-band crafting
   outcome, and never on other bands or non-crafting activities;
 - the get/increment SQL helpers issue the expected query shape.
Real-DB increment round-trip + ON DELETE CASCADE are proven in the acceptance suite
(tests/acceptance/test_crafting_skill_counter_cascade.py); the full worker E2E is
covered by the Milestone-3 capstone (story-005).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from claim_stack_helpers import patch_claim_stack

import db_mutations
import db_queries
from async_worker import _resolve_single_activity
from dialogue_parser import Segment

_CRAFTING_ACTIVITY = {
    "id": "activity_craft1",
    "player_id": "player_1",
    "activity_type": "crafting",
    "parameters": {"recipe_id": "iron_sword"},
    "resolve_at": "2026-01-01T00:00:00Z",
}


def _outcome(tier: str) -> dict:
    """A minimal outcome dict for the worker's narration/cache path."""
    return {
        "tier": tier,
        "crafted_item_id": None if tier == "failure" else "iron_sword",
        "crafted_item_name": None if tier == "failure" else "Iron Sword",
        "bonus_property": None,
        "flaw": None,
        "materials_consumed": ["iron_ingot"],
        "materials_returned": [],
        "narrative_context": {},
        "decision_options": [],
    }


async def _run_resolution(activity: dict, outcome: dict):
    """Drive _resolve_single_activity with LLM/TTS/DB mocked, returning the
    increment_crafting_skill_counter mock so callers can assert on it."""
    _mock_conn, txn_p, get_p, claim_p, revert_p = patch_claim_stack(activity)
    segments = [Segment("NARRATOR", "neutral", "It is done.")]
    with (
        txn_p,
        get_p,
        claim_p,
        revert_p,
        patch("async_worker.db_queries.get_player", new_callable=AsyncMock, return_value={"name": "Aldric"}),
        patch("async_worker._resolve_one_outcome", new_callable=AsyncMock, return_value=outcome),
        patch(
            "async_worker.generate_activity_narration",
            new_callable=AsyncMock,
            return_value=(segments, "It is done.", "Summary."),
        ),
        patch("async_worker.synthesize_segments", new_callable=AsyncMock, return_value="activity_craft1.mp3"),
        patch("async_worker.db_mutations.update_activity", new_callable=AsyncMock),
        patch("async_worker.mark_resolved", new_callable=AsyncMock, return_value=True),
        patch("async_worker.generate_notification_hook", new_callable=AsyncMock, return_value="Done."),
        patch("async_worker.send_push_notification", new_callable=AsyncMock),
        patch("async_worker.db_mutations.increment_crafting_skill_counter", new_callable=AsyncMock) as mock_increment,
    ):
        await _resolve_single_activity(activity)
    return mock_increment


class TestFailureIncrementsCounter:
    @pytest.mark.asyncio
    async def test_failure_band_increments_once(self):
        """AC#1: a crafting Failure outcome increments the player's counter by exactly 1."""
        mock_increment = await _run_resolution(_CRAFTING_ACTIVITY, _outcome("failure"))
        mock_increment.assert_awaited_once_with("player_1")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tier", ["exceptional", "success", "partial"])
    async def test_non_failure_bands_do_not_increment(self, tier):
        """AC#2: exceptional/success/partial outcomes leave the counter unchanged."""
        mock_increment = await _run_resolution(_CRAFTING_ACTIVITY, _outcome(tier))
        mock_increment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_crafting_activity_does_not_increment(self):
        """AC#2: a non-crafting activity never touches the Crafting counter, even on failure."""
        errand = {**_CRAFTING_ACTIVITY, "activity_type": "companion_errand"}
        mock_increment = await _run_resolution(errand, _outcome("failure"))
        mock_increment.assert_not_awaited()


class TestCounterSqlHelpers:
    @pytest.mark.asyncio
    async def test_increment_issues_atomic_upsert(self):
        """increment_crafting_skill_counter runs a single atomic +1 UPSERT for the player."""
        conn = MagicMock()
        conn.execute = AsyncMock()
        await db_mutations.increment_crafting_skill_counter("player_1", conn=conn)
        conn.execute.assert_awaited_once()
        sql, *args = conn.execute.call_args[0]
        assert "player_crafting_skill_counter" in sql
        assert "counter + 1" in sql
        assert args == ["player_1"]

    @pytest.mark.asyncio
    async def test_get_returns_counter_value(self):
        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=3)
        assert await db_queries.get_crafting_skill_counter("player_1", conn=conn) == 3

    @pytest.mark.asyncio
    async def test_get_defaults_to_zero_when_absent(self):
        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=None)
        assert await db_queries.get_crafting_skill_counter("player_1", conn=conn) == 0
