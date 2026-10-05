"""A mocked fetchrow cannot execute COALESCE/IN bucketing; SQL text checks are not stored-behavior proof."""

from unittest.mock import AsyncMock, patch

import db_activity_queries


def _pool_with_fetchrow(row):
    pool = AsyncMock()
    pool.fetchrow = AsyncMock(return_value=row)
    return pool


def _conn_with_execute():
    conn = AsyncMock()
    conn.execute = AsyncMock()
    return conn


class TestLockPlayerSlotRows:
    async def test_locks_both_slot_tables_with_matching_predicates(self):
        # Twin of TS lockPlayerSlotRows (activity_create.ts): FOR UPDATE on the same
        # rows count_active_by_slot reads, so a concurrent create can't pass the slot
        # check during a worker's in_progress->resolving flip. Predicates MUST match
        # count_active_by_slot's status filter.
        conn = _conn_with_execute()
        await db_activity_queries.lock_player_slot_rows("p1", conn=conn)
        sqls = [" ".join(call.args[0].split()) for call in conn.execute.call_args_list]
        joined = " || ".join(sqls)
        assert "FOR UPDATE" in joined
        assert "async_activities" in joined
        assert "data->>'status' IN ('in_progress', 'resolving')" in joined
        assert "training_activities" in joined
        assert "state != 'complete'" in joined


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
        pool = _pool_with_fetchrow({"training": 0, "crafting": 0, "companion": 0})
        mock_db.get_pool = AsyncMock(return_value=pool)
        await db_activity_queries.count_active_by_slot("p1")
        sql = " ".join(pool.fetchrow.call_args.args[0].split())
        assert "COALESCE(data->>'slot', data->>'activity_type')" in sql

    @patch("db_activity_queries.db")
    async def test_companion_bucket_matches_both_variants(self, mock_db):
        pool = _pool_with_fetchrow({"training": 0, "crafting": 0, "companion": 0})
        mock_db.get_pool = AsyncMock(return_value=pool)
        await db_activity_queries.count_active_by_slot("p1")
        sql = " ".join(pool.fetchrow.call_args.args[0].split())
        assert "src IN ('companion', 'companion_errand')" in sql

    @patch("db_activity_queries.db")
    async def test_query_unions_async_and_training_activities(self, mock_db):
        pool = _pool_with_fetchrow({"training": 0, "crafting": 0, "companion": 0})
        mock_db.get_pool = AsyncMock(return_value=pool)
        await db_activity_queries.count_active_by_slot("p1")
        sql = " ".join(pool.fetchrow.call_args.args[0].split())
        assert "UNION ALL" in sql
