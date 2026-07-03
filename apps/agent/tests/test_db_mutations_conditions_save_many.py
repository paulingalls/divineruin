"""Tests for db_mutations_conditions.save_many_player_conditions — the batched
{player_id: conditions_list} write (M4.8 story-007), replacing N per-target save_player_conditions
round-trips in the OOC condition party gate.

Two-part coverage (mirrors the db_mutations_* family): mock-conn unit asserts the SQL shape
(unnest + jsonb_set), real-PG fast-lane round-trips prove the batch write lands on every row and
touches only the requested ones.
"""

import json
from unittest.mock import AsyncMock

import db_mutations_conditions


def _cond(ctype: str) -> dict:
    return {"type": ctype, "duration": None, "source": None, "stacks": 1}


class TestSaveManyPlayerConditionsSql:
    async def test_empty_mapping_is_a_noop(self):
        conn = AsyncMock()
        await db_mutations_conditions.save_many_player_conditions({}, conn=conn)
        conn.execute.assert_not_awaited()

    async def test_one_statement_uses_unnest_and_jsonb_set(self):
        conn = AsyncMock()
        await db_mutations_conditions.save_many_player_conditions(
            {"a1": [_cond("blessed")], "a2": [_cond("inspired")]}, conn=conn
        )
        conn.execute.assert_awaited_once()  # ONE round-trip for both targets
        sql, ids, conds = conn.execute.call_args.args
        assert "UPDATE players" in sql
        assert "jsonb_set" in sql
        assert "'{conditions}'" in sql
        assert "unnest" in sql
        assert ids == ["a1", "a2"]
        assert json.loads(conds[0]) == [_cond("blessed")]
        assert json.loads(conds[1]) == [_cond("inspired")]


async def _seed_player(pool, player_id: str, *, conditions=None) -> None:
    data = {"player_id": player_id, "level": 3}
    if conditions is not None:
        data["conditions"] = conditions
    await pool.execute(
        "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
        "ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb",
        player_id,
        json.dumps(data),
    )


async def _read_conditions(pool, player_id: str):
    row = await pool.fetchrow("SELECT data->'conditions' AS c FROM players WHERE player_id = $1", player_id)
    stored = row["c"]
    return json.loads(stored) if isinstance(stored, str) else stored


async def test_batch_write_lands_on_every_target(dev_db_pool):
    pool = dev_db_pool
    a1, a2, a3 = "s007_smpc_a1", "s007_smpc_a2", "s007_smpc_a3"
    for pid in (a1, a2, a3):
        await _seed_player(pool, pid, conditions=[])
    try:
        await db_mutations_conditions.save_many_player_conditions(
            {a1: [_cond("blessed")], a2: [_cond("inspired")], a3: [_cond("blessed")]}, conn=pool
        )
        assert [c["type"] for c in await _read_conditions(pool, a1)] == ["blessed"]
        assert [c["type"] for c in await _read_conditions(pool, a2)] == ["inspired"]
        assert [c["type"] for c in await _read_conditions(pool, a3)] == ["blessed"]
    finally:
        for pid in (a1, a2, a3):
            await pool.execute("DELETE FROM players WHERE player_id = $1", pid)


async def test_batch_write_does_not_touch_unrequested_rows(dev_db_pool):
    pool = dev_db_pool
    target, bystander = "s007_smpc_target", "s007_smpc_bystander"
    await _seed_player(pool, target, conditions=[])
    await _seed_player(pool, bystander, conditions=[_cond("poisoned")])
    try:
        await db_mutations_conditions.save_many_player_conditions({target: [_cond("blessed")]}, conn=pool)
        assert [c["type"] for c in await _read_conditions(pool, target)] == ["blessed"]
        assert [c["type"] for c in await _read_conditions(pool, bystander)] == ["poisoned"]
    finally:
        for pid in (target, bystander):
            await pool.execute("DELETE FROM players WHERE player_id = $1", pid)
