"""M4.8 story-013: server-side atomic removal of spent beneficial conditions.

The consume side previously read players.data.conditions from a row fetched OUTSIDE the tx,
removed the spent die in Python, then overwrote the whole list — clobbering a concurrent
condition write (e.g. a DM-applied Poisoned). db_mutations_conditions.remove_player_conditions
removes the named types in ONE atomic SQL statement that operates on the LIVE row, so a
condition added between a stale read and the removal survives.

Two-part coverage (mirrors the db_mutations_* family): mock-conn unit asserts the jsonb_set
array-filter SQL; real-PG fast-lane round-trips prove the clobber-preservation + null tolerance.
"""

import json
from unittest.mock import AsyncMock

import db_mutations_conditions
from condition_consume import consume_beneficial_conditions


def _cond(ctype: str) -> dict:
    return {"type": ctype, "duration": None, "source": None, "stacks": 1}


class TestRemovePlayerConditionsSql:
    async def test_filters_named_types_via_jsonb_set(self):
        conn = AsyncMock()
        await db_mutations_conditions.remove_player_conditions("p1", ("blessed", "inspired"), conn=conn)
        sql, *params = conn.execute.call_args.args
        assert "UPDATE players" in sql
        assert "jsonb_set" in sql
        assert "'{conditions}'" in sql
        assert "jsonb_array_elements" in sql
        assert "ANY($2" in sql  # the consumed-type array, server-side filter
        assert params[0] == "p1"
        assert params[1] == ["blessed", "inspired"]  # asyncpg wants a list for the text[] param

    async def test_does_not_touch_other_keys(self):
        conn = AsyncMock()
        await db_mutations_conditions.remove_player_conditions("p1", ("blessed",), conn=conn)
        sql, *_ = conn.execute.call_args.args
        assert "{resonance" not in sql and "{veil_ward" not in sql and "{concentration" not in sql

    async def test_empty_types_is_a_noop(self):
        conn = AsyncMock()
        await db_mutations_conditions.remove_player_conditions("p1", (), conn=conn)
        conn.execute.assert_not_awaited()


async def _seed_conditions(pool, player_id: str, conditions) -> None:
    data = {"player_id": player_id, "attributes": {"strength": 14}, "level": 5}
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


async def test_remove_preserves_a_concurrently_present_condition(dev_db_pool):
    # Core clobber-preservation: the row holds [blessed, poisoned] (poisoned modelling a write that
    # landed after any stale read). Removing only 'blessed' leaves 'poisoned' intact — a stale
    # full-list overwrite would have dropped it.
    pool = dev_db_pool
    player_id = "s013_remove_preserves_concurrent"
    await _seed_conditions(pool, player_id, [_cond("blessed"), _cond("poisoned")])
    try:
        await db_mutations_conditions.remove_player_conditions(player_id, ("blessed",), conn=pool)
        remaining = await _read_conditions(pool, player_id)
        assert [c["type"] for c in remaining] == ["poisoned"]
    finally:
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)


async def test_remove_multiple_types_clears_them(dev_db_pool):
    pool = dev_db_pool
    player_id = "s013_remove_multiple"
    await _seed_conditions(pool, player_id, [_cond("blessed"), _cond("inspired")])
    try:
        await db_mutations_conditions.remove_player_conditions(player_id, ("blessed", "inspired"), conn=pool)
        assert await _read_conditions(pool, player_id) == []
    finally:
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)


async def test_remove_tolerates_null_conditions(dev_db_pool):
    # players.data.conditions can be JSON null (conditions.py documents it). The jsonb_typeof guard
    # must not crash on a scalar/null — there is nothing to remove, so the removal is a no-op and the
    # stored value is left untouched (downstream readers treat null as no conditions).
    pool = dev_db_pool
    player_id = "s013_remove_null_conditions"
    await pool.execute(
        "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
        "ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb",
        player_id,
        json.dumps({"player_id": player_id, "level": 5, "conditions": None}),
    )
    try:
        await db_mutations_conditions.remove_player_conditions(player_id, ("blessed",), conn=pool)
        assert await _read_conditions(pool, player_id) is None  # no-op: nothing to remove
    finally:
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)


async def test_consume_preserves_concurrent_condition_via_server_side_removal(dev_db_pool):
    # End-to-end for the 4 pure-consume modes: consume_beneficial_conditions takes only the spent
    # types (no stale player dict) and removes them server-side. The DB holds [blessed, poisoned];
    # consuming 'blessed' leaves 'poisoned' — proving no read-modify-write clobber.
    pool = dev_db_pool
    player_id = "s013_consume_preserves_concurrent"
    await _seed_conditions(pool, player_id, [_cond("blessed"), _cond("poisoned")])
    try:
        await consume_beneficial_conditions(player_id, ("blessed",), conn=pool)
        remaining = await _read_conditions(pool, player_id)
        assert [c["type"] for c in remaining] == ["poisoned"]
    finally:
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)


async def test_consume_noop_when_nothing_consumed(dev_db_pool):
    pool = dev_db_pool
    player_id = "s013_consume_noop"
    await _seed_conditions(pool, player_id, [_cond("blessed")])
    try:
        await consume_beneficial_conditions(player_id, (), conn=pool)
        remaining = await _read_conditions(pool, player_id)
        assert [c["type"] for c in remaining] == ["blessed"]
    finally:
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)
