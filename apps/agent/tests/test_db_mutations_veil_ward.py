"""Tests for the M3.2 Veil Ward DB layer (db_mutations_veil_ward, story-002).

Pass a mock conn directly (the functions accept conn=) and assert the SQL + params —
exercising the jsonb_set construction and the read-side parsing. Real SQL is exercised
against a testcontainer at tests/acceptance/test_veil_ward_persistence.py (the AC4
roundtrip), mirroring test_db_mutations_resonance.py.

Storage shape: players.data.veil_ward = {active: bool, source: str|null}, a top-level
JSONB key beside {resonance}. `active` drives the cast-path halving (story-004); `source`
is the raising archetype id, carried for narration/HUD flavor.
"""

from unittest.mock import AsyncMock

import db_mutations_veil_ward


class TestUpdatePlayerVeilWard:
    async def test_writes_active_and_source_via_jsonb_set(self):
        conn = AsyncMock()
        await db_mutations_veil_ward.update_player_veil_ward("p1", True, "cleric", conn=conn)
        sql, *params = conn.execute.call_args.args
        assert "UPDATE players" in sql
        assert "jsonb_set" in sql
        assert "'{veil_ward}'" in sql  # 1-level path: works whether or not the key pre-exists
        assert "jsonb_build_object('active'" in sql
        assert "'source'" in sql
        assert params == ["p1", True, "cleric"]

    async def test_dismiss_writes_inactive_with_null_source(self):
        conn = AsyncMock()
        await db_mutations_veil_ward.update_player_veil_ward("p1", False, None, conn=conn)
        _sql, *params = conn.execute.call_args.args
        assert params == ["p1", False, None]

    async def test_does_not_touch_other_keys(self):
        conn = AsyncMock()
        await db_mutations_veil_ward.update_player_veil_ward("p1", True, "druid", conn=conn)
        sql, *_ = conn.execute.call_args.args
        assert "{resonance" not in sql and "{focus" not in sql and "{stamina" not in sql


class TestReadPlayerVeilWard:
    async def test_parses_active_and_source(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = {"active": "true", "source": "paladin"}
        out = await db_mutations_veil_ward.read_player_veil_ward("p1", conn=conn)
        assert out == {"active": True, "source": "paladin"}

    async def test_inactive_ward(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = {"active": "false", "source": None}
        out = await db_mutations_veil_ward.read_player_veil_ward("p1", conn=conn)
        assert out == {"active": False, "source": None}

    async def test_defaults_when_row_absent(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = None
        out = await db_mutations_veil_ward.read_player_veil_ward("ghost", conn=conn)
        assert out == {"active": False, "source": None}

    async def test_defaults_when_key_absent(self):
        # Row exists but the veil_ward key was never seeded (active/source come back NULL).
        conn = AsyncMock()
        conn.fetchrow.return_value = {"active": None, "source": None}
        out = await db_mutations_veil_ward.read_player_veil_ward("p1", conn=conn)
        assert out == {"active": False, "source": None}
