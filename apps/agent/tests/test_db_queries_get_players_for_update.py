"""Tests for db_queries.get_players_for_update — the id-ordered batch FOR UPDATE fetch (M4.8
story-007), replacing N per-target get_player round-trips in the OOC condition party gate.

Two-part coverage (mirrors the db_mutations_* / db_queries family): mock-conn unit asserts the
SQL shape (ANY + ORDER BY + FOR UPDATE); real-PG fast-lane round-trips prove the batch fetch and
the "missing id absent from the map" contract.
"""

import json
from unittest.mock import AsyncMock, patch

import db_queries


def _pool_with_fetch(rows):
    pool = AsyncMock()
    pool.fetch = AsyncMock(return_value=rows)
    return pool


class TestGetPlayersForUpdateSql:
    @patch("db_queries.db")
    async def test_empty_ids_returns_empty_without_query(self, mock_db):
        pool = _pool_with_fetch([])
        mock_db.get_pool = AsyncMock(return_value=pool)
        result = await db_queries.get_players_for_update([])
        assert result == {}
        pool.fetch.assert_not_awaited()

    @patch("db_queries.db")
    async def test_query_uses_any_order_by_and_for_update(self, mock_db):
        pool = _pool_with_fetch([])
        mock_db.get_pool = AsyncMock(return_value=pool)
        await db_queries.get_players_for_update(["a1", "a2"])
        sql, ids = pool.fetch.call_args.args
        assert "= ANY($1)" in sql
        assert "ORDER BY player_id" in sql
        assert "FOR UPDATE" in sql
        assert ids == ["a1", "a2"]

    @patch("db_queries.db")
    async def test_returns_map_keyed_by_player_id(self, mock_db):
        rows = [
            {"player_id": "a1", "data": json.dumps({"player_id": "a1", "level": 3})},
            {"player_id": "a2", "data": json.dumps({"player_id": "a2", "level": 5})},
        ]
        mock_db.get_pool = AsyncMock(return_value=_pool_with_fetch(rows))
        result = await db_queries.get_players_for_update(["a1", "a2"])
        assert result == {
            "a1": {"player_id": "a1", "level": 3},
            "a2": {"player_id": "a2", "level": 5},
        }

    @patch("db_queries.db")
    async def test_id_absent_from_rows_is_absent_from_map(self, mock_db):
        rows = [{"player_id": "a1", "data": json.dumps({"player_id": "a1"})}]
        mock_db.get_pool = AsyncMock(return_value=_pool_with_fetch(rows))
        result = await db_queries.get_players_for_update(["a1", "ghost"])
        assert set(result.keys()) == {"a1"}


async def _seed_player(pool, player_id: str, *, level: int = 1) -> None:
    await pool.execute(
        "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
        "ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb",
        player_id,
        json.dumps({"player_id": player_id, "level": level, "conditions": []}),
    )


async def test_batch_fetch_returns_every_requested_row(dev_db_pool):
    pool = dev_db_pool
    ids = ["s007_gpfu_a1", "s007_gpfu_a2", "s007_gpfu_a3"]
    for pid in ids:
        await _seed_player(pool, pid, level=4)
    try:
        result = await db_queries.get_players_for_update(sorted(ids), conn=pool)
        assert set(result.keys()) == set(ids)
        for pid in ids:
            assert result[pid]["level"] == 4
    finally:
        for pid in ids:
            await pool.execute("DELETE FROM players WHERE player_id = $1", pid)


async def test_batch_fetch_omits_missing_ids(dev_db_pool):
    pool = dev_db_pool
    pid = "s007_gpfu_present"
    await _seed_player(pool, pid)
    try:
        result = await db_queries.get_players_for_update([pid, "s007_gpfu_ghost"], conn=pool)
        assert set(result.keys()) == {pid}
    finally:
        await pool.execute("DELETE FROM players WHERE player_id = $1", pid)
