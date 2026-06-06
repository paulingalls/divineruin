"""Tests for the M8 spell persistence layer (character_spells).

Pass a mock conn directly (the functions accept conn=) and assert the SQL +
params, mirroring test_ability_persistence.py. Real SQL is exercised against a
testcontainer at the story-007 capstone (ADR 0003) — the real-DB testcontainer
fixtures live in tests/acceptance/conftest.py, unreachable from tests/.

character_spells is the known ELECTIVE library (caster core spells stay
archetype_abilities rows, seam 235ae150c5d3); spell_learning_progress is in-flight
training counted in discrete cycles. acquisition_track is {training, discovery}
only — NO core track.
"""

from unittest.mock import AsyncMock

import pytest

import character_spells


class TestRecordLearned:
    async def test_upserts_with_track_and_prepared(self):
        conn = AsyncMock()
        await character_spells.record_learned("p1", "arcane_fireball", "discovery", is_prepared=True, conn=conn)
        sql, *params = conn.execute.call_args.args
        assert "INSERT INTO character_spells" in sql
        assert "ON CONFLICT (player_id, spell_id) DO NOTHING" in sql
        assert params == ["p1", "arcane_fireball", "discovery", True]

    async def test_defaults_unprepared(self):
        conn = AsyncMock()
        await character_spells.record_learned("p1", "arcane_fireball", "training", conn=conn)
        _sql, *params = conn.execute.call_args.args
        assert params == ["p1", "arcane_fireball", "training", False]

    @pytest.mark.parametrize("bad_track", ["core", "scroll", "", "Training"])
    async def test_rejects_invalid_acquisition_track(self, bad_track):
        # Electives-only contract: only training/discovery (decision m8-elective-catalog).
        conn = AsyncMock()
        with pytest.raises(ValueError, match=bad_track or "acquisition_track"):
            await character_spells.record_learned("p1", "arcane_fireball", bad_track, conn=conn)
        conn.execute.assert_not_awaited()


class TestGetKnown:
    async def test_selects_player_library(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(
            return_value=[
                {"spell_id": "arcane_fireball", "acquisition_track": "discovery", "is_prepared": True},
            ]
        )
        rows = await character_spells.get_known("p1", conn=conn)
        sql, *params = conn.fetch.call_args.args
        assert "FROM character_spells WHERE player_id = $1" in sql
        assert params == ["p1"]
        assert rows == [{"spell_id": "arcane_fireball", "acquisition_track": "discovery", "is_prepared": True}]


class TestGetPrepared:
    async def test_filters_is_prepared(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        await character_spells.get_prepared("p1", conn=conn)
        sql, *params = conn.fetch.call_args.args
        assert "FROM character_spells WHERE player_id = $1" in sql
        assert "is_prepared" in sql
        assert params == ["p1"]


class TestSetPrepared:
    async def test_updates_prepared_flag(self):
        conn = AsyncMock()
        await character_spells.set_prepared("p1", "arcane_fireball", True, conn=conn)
        sql, *params = conn.execute.call_args.args
        assert "UPDATE character_spells SET is_prepared = $3" in sql
        assert "WHERE player_id = $1 AND spell_id = $2" in sql
        assert params == ["p1", "arcane_fireball", True]


class TestAdvanceLearningCycle:
    async def test_increments_and_reports_incomplete_below_threshold(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"cycles_completed": 3, "cycles_required": 5})
        result = await character_spells.advance_learning_cycle(
            "p1", "arcane_fireball", 5, midpoint_decision_id="power", conn=conn
        )
        sql, *params = conn.fetchrow.call_args.args
        assert "INSERT INTO spell_learning_progress" in sql
        assert "ON CONFLICT (player_id, spell_id) DO UPDATE" in sql
        assert "cycles_completed = spell_learning_progress.cycles_completed + 1" in sql
        assert "RETURNING cycles_completed, cycles_required" in sql
        assert params == ["p1", "arcane_fireball", 5, "power"]
        assert result == {"cycles_completed": 3, "cycles_required": 5, "completed": False}

    async def test_reports_completed_at_threshold(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"cycles_completed": 5, "cycles_required": 5})
        result = await character_spells.advance_learning_cycle("p1", "arcane_fireball", 5, conn=conn)
        _sql, *params = conn.fetchrow.call_args.args
        # midpoint_decision_id defaults to None when not supplied.
        assert params == ["p1", "arcane_fireball", 5, None]
        assert result["completed"] is True


class TestLearningProgressHelpers:
    async def test_get_learning_progress_returns_row(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={"cycles_completed": 2, "cycles_required": 3, "midpoint_decision_id": None}
        )
        row = await character_spells.get_learning_progress("p1", "arcane_fireball", conn=conn)
        sql, *params = conn.fetchrow.call_args.args
        assert "FROM spell_learning_progress WHERE player_id = $1 AND spell_id = $2" in sql
        assert params == ["p1", "arcane_fireball"]
        assert row == {"cycles_completed": 2, "cycles_required": 3, "midpoint_decision_id": None}

    async def test_get_learning_progress_none_when_absent(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        row = await character_spells.get_learning_progress("p1", "arcane_fireball", conn=conn)
        assert row is None

    async def test_delete_learning_progress(self):
        conn = AsyncMock()
        await character_spells.delete_learning_progress("p1", "arcane_fireball", conn=conn)
        sql, *params = conn.execute.call_args.args
        assert "DELETE FROM spell_learning_progress WHERE player_id = $1 AND spell_id = $2" in sql
        assert params == ["p1", "arcane_fireball"]
