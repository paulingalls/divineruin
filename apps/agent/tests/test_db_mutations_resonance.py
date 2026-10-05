"""Derive qualitative state from current on read so storage cannot disagree."""

from unittest.mock import AsyncMock

import db_mutations_resonance


class TestUpdatePlayerResonance:
    async def test_writes_current_via_jsonb_set(self):
        conn = AsyncMock()
        await db_mutations_resonance.update_player_resonance("p1", 7, conn=conn)
        sql, *params = conn.execute.call_args.args
        assert "UPDATE players" in sql
        assert "jsonb_set" in sql
        assert "'{resonance}'" in sql  # 1-level path so it works whether or not the key pre-exists
        assert "jsonb_build_object('current'" in sql
        assert params == ["p1", 7]

    async def test_merges_into_resonance_object_to_preserve_siblings(self):
        conn = AsyncMock()
        await db_mutations_resonance.update_player_resonance("p1", 5, conn=conn)
        sql, *_ = conn.execute.call_args.args
        assert "COALESCE(data->'resonance'" in sql
        assert "||" in sql  # jsonb concat merge, not object replace

    async def test_does_not_touch_other_pools(self):
        conn = AsyncMock()
        await db_mutations_resonance.update_player_resonance("p1", 3, conn=conn)
        sql, *_ = conn.execute.call_args.args
        assert "{stamina" not in sql and "{focus" not in sql and "{hp" not in sql


class TestReadPlayerResonance:
    async def test_derives_state_from_stored_current(self):
        cases = [
            (2, "stable"),
            (4, "stable"),
            (5, "flickering"),
            (7, "flickering"),
            (8, "flickering"),
            (9, "overreach"),
            (10, "overreach"),
        ]
        for current, state in cases:
            conn = AsyncMock()
            conn.fetchrow.return_value = {"current": str(current), "flickering_bonus": "0"}
            out = await db_mutations_resonance.read_player_resonance("p1", conn=conn)
            assert out == {"current": current, "flickering_bonus": 0, "state": state}

    async def test_derives_state_with_flickering_bonus(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = {"current": "9", "flickering_bonus": "1"}
        out = await db_mutations_resonance.read_player_resonance("p1", conn=conn)
        assert out == {"current": 9, "flickering_bonus": 1, "state": "flickering"}

    async def test_defaults_when_row_absent(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = None
        out = await db_mutations_resonance.read_player_resonance("ghost", conn=conn)
        assert out == {"current": 0, "flickering_bonus": 0, "state": "stable"}

    async def test_defaults_when_key_absent(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = {"current": None, "flickering_bonus": None}  # resonance keys unset
        out = await db_mutations_resonance.read_player_resonance("p1", conn=conn)
        assert out == {"current": 0, "flickering_bonus": 0, "state": "stable"}


class TestUpdatePlayerFlickeringBonus:
    async def test_writes_flickering_bonus_via_merge(self):
        conn = AsyncMock()
        await db_mutations_resonance.update_player_flickering_bonus("p1", 1, conn=conn)
        sql, *params = conn.execute.call_args.args
        assert "UPDATE players" in sql
        assert "'{resonance}'" in sql
        assert "jsonb_build_object('flickering_bonus'" in sql
        assert "COALESCE(data->'resonance'" in sql and "||" in sql
        assert params == ["p1", 1]


class TestResetPlayerResonance:
    async def test_resets_current_to_zero(self):
        conn = AsyncMock()
        await db_mutations_resonance.reset_player_resonance("p1", conn=conn)
        sql, *params = conn.execute.call_args.args
        assert "UPDATE players" in sql
        assert params == ["p1", 0]  # reset == update-to-0 (stable)
