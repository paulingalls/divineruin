"""Tests for the M4.4 death-history DB layer (db_mutations_death, story-001).

Two-part coverage, mirroring the db_mutations_* module family: (1) mock-conn unit tests assert
the jsonb_set('{death_history}', ...) construction + read-side parsing/default; (2) one real-PG
fast-lane round-trip (single-concern, per the CLAUDE.md test-lane guidance) proves count
accumulation + the cost ledger against the dev DB at :55432.

Storage shape: players.data.death_history = {"count": int, "costs": [<DeathCost dict>, ...]},
a top-level JSONB key beside {conditions} and {resonance}. The permanent death count
never resets; record_death takes a pre-computed DeathCost (count authoritative — no self-increment).
"""

import json
from dataclasses import asdict
from unittest.mock import AsyncMock

import db_mutations_death
from death_cost import determine_death_cost


class TestReadDeathHistory:
    async def test_defaults_when_row_absent(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = None
        assert await db_mutations_death.read_death_history("ghost", conn=conn) == {"count": 0, "costs": []}

    async def test_defaults_when_key_absent(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = {"death_history": None}
        assert await db_mutations_death.read_death_history("p1", conn=conn) == {"count": 0, "costs": []}

    async def test_parses_json_string(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = {"death_history": json.dumps({"count": 3, "costs": [{"tier": "severe"}]})}
        out = await db_mutations_death.read_death_history("p1", conn=conn)
        assert out == {"count": 3, "costs": [{"tier": "severe"}]}

    async def test_passes_through_dict(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = {"death_history": {"count": 1, "costs": []}}
        out = await db_mutations_death.read_death_history("p1", conn=conn)
        assert out == {"count": 1, "costs": []}


class TestRecordDeath:
    async def test_writes_via_jsonb_set_with_authoritative_count(self):
        conn = AsyncMock()
        # Store already holds death 1 (gentle); recording death 2 (moderate) appends + advances count.
        gentle = asdict(determine_death_cost(1, level=5))
        conn.fetchrow.return_value = {"death_history": {"count": 1, "costs": [gentle]}}

        moderate = determine_death_cost(2, level=5)
        out = await db_mutations_death.record_death("p1", moderate, conn=conn)

        sql, *params = conn.execute.call_args.args
        assert "UPDATE players" in sql
        assert "jsonb_set" in sql
        assert "'{death_history}'" in sql  # 1-level path: works whether or not the key pre-exists
        assert params[0] == "p1"
        written = json.loads(params[1])
        assert written["count"] == 2  # cost.death_count is authoritative, no double-increment
        assert [c["tier"] for c in written["costs"]] == ["gentle", "moderate"]
        assert out == written

    async def test_does_not_touch_other_keys(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = {"death_history": None}
        await db_mutations_death.record_death("p1", determine_death_cost(1, level=5), conn=conn)
        sql, *_ = conn.execute.call_args.args
        assert "{conditions" not in sql and "{resonance" not in sql and "{veil_ward" not in sql


async def _seed_player(pool, player_id: str) -> None:
    await pool.execute(
        "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
        "ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb",
        player_id,
        json.dumps({"player_id": player_id, "attributes": {"strength": 14}, "level": 5}),
    )


async def test_record_then_read_roundtrips_count_and_ledger(dev_db_pool):
    pool = dev_db_pool
    player_id = "s001_death_history_roundtrip"
    await _seed_player(pool, player_id)
    try:
        assert await db_mutations_death.read_death_history(player_id, conn=pool) == {"count": 0, "costs": []}

        await db_mutations_death.record_death(player_id, determine_death_cost(1, level=5), conn=pool)
        await db_mutations_death.record_death(player_id, determine_death_cost(2, level=5), conn=pool)

        history = await db_mutations_death.read_death_history(player_id, conn=pool)
        assert history["count"] == 2
        assert [c["tier"] for c in history["costs"]] == ["gentle", "moderate"]
        assert history["costs"][1]["attribute_target"] == "lowest"
    finally:
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)
