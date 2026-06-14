"""Tests for the M3.4 concentration system (story-002).

Two layers, both DB-free:
- concentration.py — the pure rules engine (no IO, same discipline as resonance.py):
  check_concentration(damage) returns the save DC; concentration_holds resolves a CON
  save against that DC, with incapacitation an auto-fail.
- db_mutations_concentration.py — the persistence seam (mock-conn unit tests asserting the
  jsonb_set SQL + params, mirroring test_db_mutations_veil_ward.py). Real PG is exercised at
  tests/acceptance/test_concentration_persistence.py (AC5 roundtrip).

Storage shape: players.data.concentration = {spell_id: str|null}, a top-level JSONB key beside
{resonance} and {veil_ward}. The single active concentration spell id; null means not
concentrating. The cast keystone (story-006) reads spell.concentration, sets this on a
concentration cast, and ends any prior one (single-concentration enforcement) — not this story.
"""

from unittest.mock import AsyncMock

import pytest

import concentration
import db_mutations_concentration
from session_data import ConcentrationState, SessionData

# --- check_concentration (save DC) --------------------------------------------


@pytest.mark.parametrize(
    "damage,expected_dc",
    [
        (0, 10),  # no damage -> floor of 10
        (1, 10),
        (18, 10),  # 18//2 = 9 -> floored to 10
        (19, 10),  # 19//2 = 9 -> floored to 10
        (20, 10),  # 20//2 = 10 -> exactly the floor
        (21, 10),  # 21//2 = 10
        (22, 11),  # 22//2 = 11 -> above the floor
        (50, 25),
    ],
)
def test_check_concentration_dc_is_max_10_half_damage(damage, expected_dc):
    assert concentration.check_concentration(damage) == expected_dc


def test_check_concentration_rejects_negative_damage():
    with pytest.raises(ValueError, match="damage"):
        concentration.check_concentration(-1)


# --- concentration_holds (save resolution) ------------------------------------


def test_concentration_holds_on_meeting_dc():
    # save_total >= dc maintains concentration (a met DC succeeds).
    assert concentration.concentration_holds(15, 15) is True
    assert concentration.concentration_holds(16, 15) is True


def test_concentration_broken_below_dc():
    assert concentration.concentration_holds(14, 15) is False


def test_incapacitation_auto_fails_regardless_of_roll():
    # An incapacitated caster auto-fails even on an otherwise-passing roll.
    assert concentration.concentration_holds(99, 10, incapacitated=True) is False


def test_concentration_holds_rejects_negative_save_total():
    # A CON save total is never negative -> fail loud (symmetric with check_concentration).
    with pytest.raises(ValueError, match="save_total"):
        concentration.concentration_holds(-1, 10)


def test_incapacitation_short_circuits_before_save_validation():
    # Incapacitation auto-fails without consulting the roll, so a malformed (negative)
    # save_total is never validated on that path — the guard protects the comparison only.
    assert concentration.concentration_holds(-5, 10, incapacitated=True) is False


# --- ConcentrationState (session) ---------------------------------------------


def test_session_concentration_defaults_to_inactive():
    sd = SessionData(player_id="p1", location_id="loc1")
    assert isinstance(sd.concentration, ConcentrationState)
    assert sd.concentration.spell_id is None
    assert sd.concentration.is_active is False


def test_concentration_state_is_active_when_spell_set():
    assert ConcentrationState(spell_id="arcane_fly").is_active is True


# --- db_mutations_concentration: update ---------------------------------------


class TestUpdatePlayerConcentration:
    async def test_writes_spell_id_via_one_level_jsonb_set(self):
        conn = AsyncMock()
        await db_mutations_concentration.update_player_concentration("p1", "arcane_fly", conn=conn)
        sql, *params = conn.execute.call_args.args
        assert "UPDATE players" in sql
        assert "jsonb_set" in sql
        assert "'{concentration}'" in sql  # 1-level path: works whether or not the key pre-exists
        assert "jsonb_build_object('spell_id'" in sql
        assert params == ["p1", "arcane_fly"]

    async def test_end_writes_null_spell_id(self):
        conn = AsyncMock()
        await db_mutations_concentration.update_player_concentration("p1", None, conn=conn)
        _sql, *params = conn.execute.call_args.args
        assert params == ["p1", None]

    async def test_does_not_touch_other_keys(self):
        conn = AsyncMock()
        await db_mutations_concentration.update_player_concentration("p1", "arcane_fly", conn=conn)
        sql, *_ = conn.execute.call_args.args
        assert "{resonance" not in sql and "{veil_ward" not in sql and "{focus" not in sql


# --- db_mutations_concentration: read -----------------------------------------


class TestReadPlayerConcentration:
    async def test_parses_active_spell(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = {"spell_id": "arcane_fly"}
        out = await db_mutations_concentration.read_player_concentration("p1", conn=conn)
        assert out == {"spell_id": "arcane_fly"}

    async def test_defaults_when_spell_id_null(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = {"spell_id": None}
        out = await db_mutations_concentration.read_player_concentration("p1", conn=conn)
        assert out == {"spell_id": None}

    async def test_defaults_when_row_absent(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = None
        out = await db_mutations_concentration.read_player_concentration("ghost", conn=conn)
        assert out == {"spell_id": None}
