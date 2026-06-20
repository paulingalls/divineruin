"""Resurrection persistence (M4.4 story-003).

Mock-conn unit tests assert the jsonb_set construction + params for the resurrection writes, and a
real-PG fast-lane round-trip (dev_db_pool) proves the cost deltas + revive persist on the dev DB.
Storage: players.data.attributes.<attr> (penalty), data.maxhp_override (negative, accumulates),
data.hp.current + data.location_id (revive), data.last_rested_settlement_id (anchor tier-3)."""

import json
from unittest.mock import AsyncMock

import db_mutations_resurrection as dmr
import db_queries


class TestApplyAttributePenalty:
    async def test_writes_attribute_path_delta(self):
        conn = AsyncMock()
        await dmr.apply_attribute_penalty("p1", "strength", -1, conn=conn)
        sql, *params = conn.execute.call_args.args
        assert "UPDATE players" in sql
        assert "jsonb_set" in sql
        assert "attributes" in sql
        assert params == ["p1", "strength", -1]

    async def test_rejects_unknown_attribute(self):
        conn = AsyncMock()
        try:
            await dmr.apply_attribute_penalty("p1", "luck", -1, conn=conn)
            raise AssertionError("expected ValueError")
        except ValueError:
            pass


class TestMaxhpOverride:
    async def test_applies_negative_delta_via_jsonb_set(self):
        conn = AsyncMock()
        await dmr.apply_maxhp_override_delta("p1", -10, conn=conn)
        sql, *params = conn.execute.call_args.args
        assert "jsonb_set" in sql and "maxhp_override" in sql
        assert params == ["p1", -10]


class TestRevivePlayer:
    async def test_sets_hp_and_location(self):
        conn = AsyncMock()
        await dmr.revive_player("p1", "accord_market_square", 1, conn=conn)
        # location + hp.current writes (one or two execute calls)
        calls = [c.args[0] for c in conn.execute.call_args_list]
        joined = " ".join(calls)
        assert "location_id" in joined and "hp" in joined


class TestLastRested:
    async def test_set_and_read(self):
        conn = AsyncMock()
        await dmr.set_last_rested_settlement("p1", "millhaven", conn=conn)
        sql, *params = conn.execute.call_args.args
        assert "last_rested_settlement_id" in sql
        assert params == ["p1", json.dumps("millhaven")]  # string written as a jsonb value

    async def test_read_defaults_none_when_absent(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = {"last_rested_settlement_id": None}
        assert await dmr.read_last_rested_settlement("p1", conn=conn) is None


async def _seed_player(pool, player_id):
    await pool.execute(
        "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
        "ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb",
        player_id,
        json.dumps(
            {
                "player_id": player_id,
                "class": "warrior",
                "attributes": {"strength": 14, "charisma": 8},
                "level": 10,
                "hp": {"current": 0, "max": 60},
                "location_id": "wild_r3",
            }
        ),
    )


async def test_resurrection_writes_roundtrip(dev_db_pool):
    pool = dev_db_pool
    player_id = "s003_resurrection_roundtrip"
    await _seed_player(pool, player_id)
    try:
        await dmr.apply_attribute_penalty(player_id, "strength", -1, conn=pool)
        await dmr.apply_maxhp_override_delta(player_id, -10, conn=pool)
        await dmr.set_last_rested_settlement(player_id, "millhaven", conn=pool)
        await dmr.revive_player(player_id, "accord_market_square", 1, conn=pool)

        player = await db_queries.get_player(player_id, conn=pool)
        assert player is not None
        assert player["attributes"]["strength"] == 13  # -1
        assert player["maxhp_override"] == -10
        assert player["location_id"] == "accord_market_square"
        assert player["hp"]["current"] == 1
        assert await dmr.read_last_rested_settlement(player_id, conn=pool) == "millhaven"

        # Accumulation: a second 7+ death deepens the override.
        await dmr.apply_maxhp_override_delta(player_id, -10, conn=pool)
        player2 = await db_queries.get_player(player_id, conn=pool)
        assert player2 is not None
        assert player2["maxhp_override"] == -20
    finally:
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)
