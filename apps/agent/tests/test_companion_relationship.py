"""Tests for the pure companion relationship tier math + gate registry (M6.4 / story-003).

The HYBRID model: session_count -> floor tier (spec bands), affinity nudges up one band, never
below floor, capped at 5. These tests own the pure contract; DB persistence/query is tested in
tests/companion/test_relationship_persistence.py.
"""

from unittest.mock import AsyncMock, patch

import pytest

import companion_relationship_queries
from companion_relationship import (
    AFFINITY_PER_TIER,
    RELATIONSHIP_TIERS,
    apply_relationship_change,
    effective_tier_rank,
    tier_name,
    tier_rank_for_session_count,
    unlocks_up_to,
)
from session_data import CompanionState


class TestSessionFloor:
    @pytest.mark.parametrize(
        "count,rank",
        [(0, 1), (1, 1), (2, 1), (3, 2), (5, 2), (6, 3), (10, 3), (11, 4), (20, 4), (21, 5), (99, 5)],
    )
    def test_band_boundaries(self, count, rank):
        assert tier_rank_for_session_count(count) == rank


class TestEffectiveRank:
    def test_floor_with_zero_affinity(self):
        assert effective_tier_rank(0, 0) == 1
        assert effective_tier_rank(6, 0) == 3
        assert effective_tier_rank(21, 0) == 5

    def test_affinity_nudges_one_band_at_threshold(self):
        # session_count 6 -> floor 3; affinity 3 nudges to 4.
        assert effective_tier_rank(6, AFFINITY_PER_TIER) == 4
        assert effective_tier_rank(6, AFFINITY_PER_TIER - 1) == 3

    def test_never_below_floor(self):
        # low session, high affinity -> still at least the floor, at most +1.
        assert effective_tier_rank(0, 100) == 2  # floor 1 + 1

    def test_capped_at_5(self):
        assert effective_tier_rank(21, 100) == 5  # floor 5, nudge can't exceed 5

    def test_nudge_is_single_band(self):
        # affinity never adds more than one band regardless of magnitude.
        assert effective_tier_rank(3, 999) == 3  # floor 2 + 1


class TestTierName:
    def test_round_trip(self):
        for i, name in enumerate(RELATIONSHIP_TIERS, start=1):
            assert tier_name(i) == name

    @pytest.mark.parametrize("bad", [0, 6, -1, 7])
    def test_fail_loud_out_of_range(self, bad):
        with pytest.raises(ValueError):
            tier_name(bad)


class TestApplyRelationshipChange:
    def test_increment(self):
        assert apply_relationship_change(2, 1) == 3

    def test_clamps_at_zero(self):
        assert apply_relationship_change(0, -1) == 0
        assert apply_relationship_change(1, -5) == 0

    def test_accumulation(self):
        a = 0
        for _ in range(4):
            a = apply_relationship_change(a, 1)
        assert a == 4


class TestUnlocksUpTo:
    # Kael-shaped relationship_unlocks (story-001): only trusted/bonded/legendary have reveals.
    UNLOCKS = {
        "trusted": ["first hint of his past"],
        "bonded": ["full secret"],
        "legendary": ["story force"],
    }

    def test_low_tiers_no_reveals(self):
        assert unlocks_up_to(self.UNLOCKS, 1) == []
        assert unlocks_up_to(self.UNLOCKS, 2) == []

    def test_trusted_unlocks_trusted_only(self):
        assert unlocks_up_to(self.UNLOCKS, 3) == ["first hint of his past"]

    def test_legendary_unlocks_all_in_order(self):
        assert unlocks_up_to(self.UNLOCKS, 5) == [
            "first hint of his past",
            "full secret",
            "story force",
        ]

    def test_none_unlocks_empty(self):
        assert unlocks_up_to(None, 5) == []


class TestAssignedCompanionHydration:
    @pytest.mark.asyncio
    async def test_seeds_and_hydrates_the_companion_the_archetype_selects(self):
        lira = CompanionState(id="companion_lira", name="Lira", session_count=1)
        with (
            patch(
                "db_mutations_companion.insert_companion_relationship_if_absent",
                new_callable=AsyncMock,
                return_value=True,
            ) as insert,
            patch(
                "companion_relationship_queries.hydrate_companion_state",
                new_callable=AsyncMock,
                return_value=lira,
            ) as hydrate,
        ):
            result = await companion_relationship_queries.hydrate_assigned_companion_state("player_1", "warrior")

        insert.assert_awaited_once_with("player_1", "companion_lira")
        hydrate.assert_awaited_once_with("player_1", "companion_lira", "Lira")
        assert result is lira

    @pytest.mark.asyncio
    async def test_unselectable_archetype_writes_nothing(self):
        """Drives the REAL selector: mocking it here would only prove a mock re-raises."""
        with (
            patch(
                "db_mutations_companion.insert_companion_relationship_if_absent",
                new_callable=AsyncMock,
            ) as insert,
            patch(
                "companion_relationship_queries.hydrate_companion_state",
                new_callable=AsyncMock,
            ) as hydrate,
            pytest.raises(ValueError, match="necromancer"),
        ):
            await companion_relationship_queries.hydrate_assigned_companion_state("player_1", "necromancer")

        insert.assert_not_awaited()
        hydrate.assert_not_awaited()
