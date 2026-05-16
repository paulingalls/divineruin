"""Hybrid counter integration test (M1.2).

Pins the production contract: session-use (`check_tools._request_skill_check_impl`)
and training-skill-practice (`async_worker.apply_skill_practice_advancement`) both
read and write the SAME `skill_advancement` row keyed by `(player_id, skill_id)`.

If a future refactor splits one path onto a different row, this test breaks.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from async_worker import apply_skill_practice_advancement
from check_tools import _request_skill_check_impl
from tests.test_mechanics_tools import SAMPLE_PLAYER, _make_context, _make_mock_room


def _shared_skill_advancement_store():
    """Build mock queries+mutations backed by a single in-memory dict keyed by (player_id, skill)."""
    store: dict[tuple[str, str], dict] = {}

    async def fake_get_single_skill_advancement(player_id: str, skill: str) -> dict:
        key = (player_id, skill)
        if key not in store:
            store[key] = {"tier": "untrained", "use_counter": 0, "narrative_moment_ready": False}
        return dict(store[key])

    async def fake_update_skill_advancement(player_id: str, skill: str, new_tier: str, new_use_count: int) -> None:
        store[(player_id, skill)] = {
            "tier": new_tier,
            "use_counter": new_use_count,
            "narrative_moment_ready": store.get((player_id, skill), {}).get("narrative_moment_ready", False),
        }

    async def fake_clear_narrative_moment(player_id: str, skill: str) -> None:
        if (player_id, skill) in store:
            store[(player_id, skill)]["narrative_moment_ready"] = False

    queries = MagicMock()
    queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
    queries.get_single_skill_advancement = AsyncMock(side_effect=fake_get_single_skill_advancement)

    mutations = MagicMock()
    mutations.update_skill_advancement = AsyncMock(side_effect=fake_update_skill_advancement)
    mutations.clear_narrative_moment = AsyncMock(side_effect=fake_clear_narrative_moment)

    return store, queries, mutations


class TestHybridCounterSharedRow:
    """M1.2 acceptance: session-use and skill_practice training both increment one row."""

    @pytest.mark.asyncio
    async def test_session_use_and_training_share_skill_advancement_row(self) -> None:
        """Running session-use then training on the same player+skill mutates the same row cumulatively."""
        store, queries, mutations = _shared_skill_advancement_store()
        player_id = "player_1"
        skill = "athletics"

        # Seed: counter starts at 0
        # Path 1: session use → counter becomes 1
        ctx = _make_context(player_id=player_id, room=_make_mock_room())
        result = json.loads(
            await _request_skill_check_impl(
                ctx,
                skill=skill,
                difficulty="moderate",
                context_description="climbing",
                queries=queries,
                mutations=mutations,
            )
        )
        assert "error" not in result
        assert store[(player_id, skill)]["use_counter"] == 1

        # Path 2: training skill_practice (counter_increment=2 for 'fundamentals') → counter becomes 3
        adv_info = await apply_skill_practice_advancement(
            player_id, skill, counter_increment=2, queries=queries, mutations=mutations
        )
        assert adv_info is not None
        assert store[(player_id, skill)]["use_counter"] == 3

        # Both paths read from and wrote to (player_id, skill) — exactly one row in the store.
        assert len(store) == 1
        assert (player_id, skill) in store

    @pytest.mark.asyncio
    async def test_training_then_session_use_crosses_tier_threshold(self) -> None:
        """Training first, then session-use — combined increments trigger the trained-tier advancement at 8."""
        store, queries, mutations = _shared_skill_advancement_store()
        player_id = "player_1"
        skill = "athletics"

        # Pre-seed the row at counter=6, untrained tier
        store[(player_id, skill)] = {"tier": "untrained", "use_counter": 6, "narrative_moment_ready": False}

        # Training skill_practice with counter_increment=2 → counter=8 → advance to trained
        adv_info = await apply_skill_practice_advancement(
            player_id, skill, counter_increment=2, queries=queries, mutations=mutations
        )
        assert adv_info == {"advanced": True, "new_tier": "trained"}
        assert store[(player_id, skill)] == {
            "tier": "trained",
            "use_counter": 8,
            "narrative_moment_ready": False,
        }

        # Subsequent session-use reads the trained tier from the SAME row
        ctx = _make_context(player_id=player_id, room=_make_mock_room())
        result = json.loads(
            await _request_skill_check_impl(
                ctx,
                skill=skill,
                difficulty="moderate",
                context_description="climbing again",
                queries=queries,
                mutations=mutations,
            )
        )
        assert "error" not in result
        # Counter advances by 1 from session-use, still on the same row
        assert store[(player_id, skill)]["use_counter"] == 9
        assert store[(player_id, skill)]["tier"] == "trained"

    @pytest.mark.asyncio
    async def test_different_skills_use_different_rows(self) -> None:
        """Sanity: different skills key to different rows; the hybrid claim is per-(player, skill)."""
        store, queries, mutations = _shared_skill_advancement_store()
        player_id = "player_1"

        await apply_skill_practice_advancement(
            player_id, "athletics", counter_increment=1, queries=queries, mutations=mutations
        )
        await apply_skill_practice_advancement(
            player_id, "stealth", counter_increment=1, queries=queries, mutations=mutations
        )

        assert store[(player_id, "athletics")]["use_counter"] == 1
        assert store[(player_id, "stealth")]["use_counter"] == 1
        assert len(store) == 2
