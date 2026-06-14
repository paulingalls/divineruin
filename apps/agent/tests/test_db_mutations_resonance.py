"""Tests for the M3.1 Resonance DB layer (db_mutations_resonance, story-002).

Pass a mock conn directly (the functions accept conn=) and assert the SQL +
params — exercising the jsonb_set construction and the read-side state derivation.
Real SQL is exercised against a testcontainer at the story-005 M3.1 capstone
(ADR 0003), mirroring test_ability_persistence.py / test_db_mutations.py.

Storage shape: players.data.resonance.current (int) is the authoritative value;
the stable/flickering/overreach STATE is always re-derived via
resonance.get_resonance_state on read (single source of truth, no drift).
"""

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
        # The write MERGES current into the existing {resonance} object (COALESCE + ||) rather than
        # REPLACING it, so a persisted flickering_bonus survives a resonance update (M3.5).
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
        # current is stored; state is derived via resonance.get_resonance_state.
        # Includes the band-edge values (4/5, 8/9) so the read-derivation contract
        # guards an off-by-one even before the story-005 real-DB round-trip lands.
        # flickering_bonus is now part of the returned shape (default 0).
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
        # The Thessyn band-shift (M3.5): a persisted flickering_bonus of 1 moves the bands up, so
        # current 9 reads "flickering" (vs "overreach" at bonus 0) — the single persisted source
        # read_player_resonance and a fresh-session hydration both derive from.
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
        # Persists flickering_bonus at {resonance,flickering_bonus} via the same sibling-preserving
        # merge (so it never clobbers current).
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
