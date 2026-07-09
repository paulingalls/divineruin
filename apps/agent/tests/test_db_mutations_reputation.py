"""Tests for the player faction-reputation writer (story-002, M23).

Real-PG round-trip against the shared dev DB at :55432 (fast lane; conftest auto-starts
docker) — the additive upsert lives in SQL, so real PG is the meaningful coverage. Proves:
a new row starts at the delta, repeated shifts accrue atomically, a legacy value-less row
starts from 0 (COALESCE), the reader sees the written value, and reason is stored. Isolates
via a unique player_id + cleanup. Plus a mock-conn arg-forwarding guard.
"""

import json
import uuid
from unittest.mock import AsyncMock

import pytest

import db
import db_mutations_reputation
from db_queries import get_player_faction_reputation

pytestmark = pytest.mark.usefixtures("dev_db_pool")

_FACTION = "accord_guild"


async def _seed_player(player_id: str) -> None:
    # player_reputation.player_id has a FK to players — seed a minimal row first.
    pool = await db.get_pool()
    await pool.execute(
        "INSERT INTO players (player_id, data) VALUES ($1, '{}'::jsonb) ON CONFLICT (player_id) DO NOTHING",
        player_id,
    )


async def _cleanup(player_id: str) -> None:
    pool = await db.get_pool()
    await pool.execute("DELETE FROM player_reputation WHERE player_id = $1", player_id)
    await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)


async def test_new_row_starts_at_delta_and_returns_it():
    player_id = f"test_rep_{uuid.uuid4().hex}"
    try:
        await _seed_player(player_id)
        new_value = await db_mutations_reputation.adjust_player_faction_reputation(
            player_id, _FACTION, 5, "completed_faction_quest"
        )
        assert new_value == 5
        assert await get_player_faction_reputation(player_id, _FACTION) == 5
    finally:
        await _cleanup(player_id)


async def test_repeated_shifts_accrue_atomically():
    player_id = f"test_rep_{uuid.uuid4().hex}"
    try:
        await _seed_player(player_id)
        await db_mutations_reputation.adjust_player_faction_reputation(player_id, _FACTION, 5, "aided")
        final = await db_mutations_reputation.adjust_player_faction_reputation(player_id, _FACTION, -3, "killed")
        assert final == 2
        assert await get_player_faction_reputation(player_id, _FACTION) == 2
    finally:
        await _cleanup(player_id)


async def test_legacy_valueless_row_starts_from_zero():
    player_id = f"test_rep_{uuid.uuid4().hex}"
    pool = await db.get_pool()
    try:
        await _seed_player(player_id)
        await pool.execute(
            "INSERT INTO player_reputation (player_id, faction_id, data) VALUES ($1, $2, '{}'::jsonb)",
            player_id,
            _FACTION,
        )
        new_value = await db_mutations_reputation.adjust_player_faction_reputation(player_id, _FACTION, 2, "aided")
        assert new_value == 2
    finally:
        await _cleanup(player_id)


async def test_reason_is_stored():
    player_id = f"test_rep_{uuid.uuid4().hex}"
    pool = await db.get_pool()
    try:
        await _seed_player(player_id)
        await db_mutations_reputation.adjust_player_faction_reputation(
            player_id, _FACTION, 5, "completed_faction_quest"
        )
        row = await pool.fetchrow(
            "SELECT data FROM player_reputation WHERE player_id = $1 AND faction_id = $2",
            player_id,
            _FACTION,
        )
        assert json.loads(row["data"])["reason"] == "completed_faction_quest"
    finally:
        await _cleanup(player_id)


async def test_forwards_args_to_conn():
    conn = AsyncMock()
    conn.fetchval.return_value = 7
    result = await db_mutations_reputation.adjust_player_faction_reputation("p1", "f1", 2, "aided", conn=conn)
    assert result == 7
    args = conn.fetchval.await_args.args
    assert args[1:] == ("p1", "f1", 2, "aided")
    assert "INSERT INTO player_reputation" in args[0]
