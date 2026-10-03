"""Diagnostic refresh preserves progressed gameplay and world records."""

import json

import pytest
from acceptance.choir_capstone_harness import reseed_choir_content

import db


@pytest.mark.asyncio
async def test_diagnostic_refresh_preserves_unrelated_progress(reset_db_pool):
    pool = await db.get_pool()
    records = []
    for table, key in [("players", "player_id"), ("npc_state", "npc_id"), ("god_agent_state", "god_id")]:
        row = await pool.fetchrow(f"SELECT {key}, data FROM {table} ORDER BY {key} LIMIT 1")
        assert row is not None
        progressed = json.loads(row["data"]) | {"xp": 90000, "level": 16, "progress_flag": "retained"}
        await pool.execute(f"UPDATE {table} SET data=$1::jsonb WHERE {key}=$2", json.dumps(progressed), row[key])
        records.append((table, key, row[key], progressed))
    await reseed_choir_content(pool)
    for table, key, identity, expected in records:
        saved = await pool.fetchval(f"SELECT data FROM {table} WHERE {key}=$1", identity)
        assert json.loads(saved) == expected
