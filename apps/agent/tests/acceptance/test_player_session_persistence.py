"""Capstone: player session_count persistence end-to-end against a real Postgres testcontainer.

story-002 (M3.5) adds a per-player session counter at players.data{session_count}, consumed by
story-003 to gate the Thessyn "Deep Adaptation" flickering bonus (10+ sessions). The mock-conn
units assert the SQL shape; this proves the JSONB round-trip on real PG — crucially the atomic
UPDATE...RETURNING arithmetic (absent key -> 1, then 1 -> 2), the fail-loud on a missing player
row, and that the jsonb_set write touches ONLY {session_count} and leaves sibling keys intact.
Auto-marked `acceptance` by tests/acceptance/conftest.py; distinct player_id since the
testcontainer DB is shared across the session.
"""

from __future__ import annotations

import json

import pytest
from acceptance.seeds import seed_player

import db
import player_session


async def test_session_count_increments_atomically_from_absent_key(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    player_id = "cap_session_counter"
    await seed_player(pool, player_id=player_id)

    # A fresh row has no session_count key -> COALESCE default 0, first increment yields 1.
    assert await player_session.hydrate_player_session(player_id, conn=pool) == 1
    # The persisted value advances by exactly one per fresh session.
    assert await player_session.hydrate_player_session(player_id, conn=pool) == 2
    assert await player_session.hydrate_player_session(player_id, conn=pool) == 3

    row = await pool.fetchrow(
        "SELECT (data->>'session_count')::int AS c FROM players WHERE player_id = $1",
        player_id,
    )
    assert row["c"] == 3


async def test_increment_leaves_sibling_keys_intact(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    player_id = "cap_session_sibling"
    await seed_player(pool, player_id=player_id)

    before = await pool.fetchrow("SELECT data FROM players WHERE player_id = $1", player_id)
    before_data = before["data"]
    # asyncpg may hand back JSONB as a str depending on codec config; both paths assert siblings.
    if isinstance(before_data, str):
        before_data = json.loads(before_data)

    await player_session.hydrate_player_session(player_id, conn=pool)

    after = await pool.fetchrow("SELECT data FROM players WHERE player_id = $1", player_id)
    after_data = after["data"]
    if isinstance(after_data, str):
        after_data = json.loads(after_data)

    assert after_data["session_count"] == 1
    # Every key that existed before the write still carries its original value.
    for key, value in before_data.items():
        if key == "session_count":
            continue
        assert after_data[key] == value


async def test_fails_loud_on_unknown_player(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    with pytest.raises(ValueError):
        await player_session.hydrate_player_session("cap_session_ghost", conn=pool)
