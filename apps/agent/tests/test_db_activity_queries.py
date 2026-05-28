"""Tests for db_activity_queries slot accounting.

Mocked-pool unit tests (like test_db_queries.py): patch db_activity_queries.db, assert
the Python wrapping (row->dict mapping) and the SQL parity guard against the TS twin
(activity_create.ts countActiveBySlot). Real SQL bucketing is exercised against a
testcontainer at the capstone (story-005, ADR 0003) — the COALESCE/IN semantics can't
be observed through a mocked fetchrow, so here we assert the query text matches TS.
"""

from unittest.mock import AsyncMock, patch

import db_activity_queries


def _pool_with_fetchrow(row):
    pool = AsyncMock()
    pool.fetchrow = AsyncMock(return_value=row)
    return pool


class TestCountActiveBySlot:
    @patch("db_activity_queries.db")
    async def test_maps_row_to_slot_dict(self, mock_db):
        pool = _pool_with_fetchrow({"training": 1, "crafting": 2, "companion": 0})
        mock_db.get_pool = AsyncMock(return_value=pool)
        assert await db_activity_queries.count_active_by_slot("p1") == {
            "training": 1,
            "crafting": 2,
            "companion": 0,
        }

    @patch("db_activity_queries.db")
    async def test_zero_dict_when_no_row(self, mock_db):
        mock_db.get_pool = AsyncMock(return_value=_pool_with_fetchrow(None))
        assert await db_activity_queries.count_active_by_slot("p1") == {
            "training": 0,
            "crafting": 0,
            "companion": 0,
        }

    @patch("db_activity_queries.db")
    async def test_buckets_by_slot_coalesced_over_activity_type(self, mock_db):
        # Parity with TS countActiveBySlot (activity_create.ts): a borrowed-training-slot
        # craft stamps data.slot='training' and MUST count toward training, not crafting.
        pool = _pool_with_fetchrow({"training": 0, "crafting": 0, "companion": 0})
        mock_db.get_pool = AsyncMock(return_value=pool)
        await db_activity_queries.count_active_by_slot("p1")
        sql = " ".join(pool.fetchrow.call_args.args[0].split())
        assert "COALESCE(data->>'slot', data->>'activity_type')" in sql

    @patch("db_activity_queries.db")
    async def test_companion_bucket_matches_both_variants(self, mock_db):
        # TS matches IN ('companion','companion_errand'); the Python twin must too.
        pool = _pool_with_fetchrow({"training": 0, "crafting": 0, "companion": 0})
        mock_db.get_pool = AsyncMock(return_value=pool)
        await db_activity_queries.count_active_by_slot("p1")
        sql = " ".join(pool.fetchrow.call_args.args[0].split())
        assert "src IN ('companion', 'companion_errand')" in sql

    @patch("db_activity_queries.db")
    async def test_query_unions_async_and_training_activities(self, mock_db):
        # Slots are counted across both async_activities and training_activities.
        pool = _pool_with_fetchrow({"training": 0, "crafting": 0, "companion": 0})
        mock_db.get_pool = AsyncMock(return_value=pool)
        await db_activity_queries.count_active_by_slot("p1")
        sql = " ".join(pool.fetchrow.call_args.args[0].split())
        assert "UNION ALL" in sql
