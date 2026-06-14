"""Capstone: M3.3 spell casting end-to-end against a real Postgres testcontainer.

stories 001-005 + 008 shipped the M3.3 catalog + cast path with mock-conn / unit
coverage. This capstone proves the Python cast surfaces compose against ONE seeded
testcontainer (auto-marked `acceptance` by tests/acceptance/conftest.py), catching
loader / JSONB seams the mocked unit tests can't:

- spells.load_spells reads the seeded 87-spell catalog from real PG, carrying the
  reconciled 4-field M3.3 schema (post story-008: no per-row level_requirement).
- spell_casting._cast_spell_impl gates + deducts Focus, accrues Resonance, and
  persists both into players.data JSONB — composed on real PG, nothing mocked.
- Resonance state is always DERIVED on read (resonance.get_resonance_state), never
  stored (no-number spec, magic.md:98).

Each test uses a distinct player_id since the testcontainer DB is shared across the
session. cast_spell gates ONLY Focus (story-004), so a Focus-funded player casts any
id without archetype/level gating.
"""

from __future__ import annotations

from dataclasses import asdict
from unittest.mock import MagicMock

from acceptance.seeds import seed_player_with_pools

import db
import db_mutations_resonance
import db_queries
import resonance
import spells
from session_data import SessionData
from spell_casting import _cast_spell_impl

# The 4 M3.3 cast-time fields the loader is strict on after story-008 deleted the
# orphaned per-row level_requirement (decision spell-loader-strict-contract, 5->4).
_M33_FIELDS = ("resonance_by_source", "terrain_effects", "audio_cue", "concentration")

# An affordable arcane spell: ceil(5 * 0.6) = 3 Resonance per cast. Three casts walk
# the spec bands stable(3) -> flickering(6) -> overreach(9). Focus-only gate (story-004).
_SPELL_ID = "arcane_fireball"


def _make_ctx(player_id: str) -> MagicMock:
    """A RunContext whose userdata is a real SessionData (room=None -> event bus only)."""
    ctx = MagicMock()
    ctx.userdata = SessionData(player_id=player_id, location_id="accord_guild_hall", room=None)
    return ctx


async def _focus_current(player_id: str) -> int:
    """Read the Focus pool back from players.data JSONB on real PG."""
    player = await db_queries.get_player(player_id, conn=await db.get_pool())
    assert player is not None
    return player["focus"]["current"]


async def test_catalog_loads_with_reconciled_m33_schema(reset_db_pool: str) -> None:
    """All 87 spells load from real PG carrying the 4 M3.3 fields and no level_requirement."""
    await spells.load_spells()
    loaded = (
        spells.get_spells_by_source("arcane")
        + spells.get_spells_by_source("divine")
        + spells.get_spells_by_source("primal")
    )
    assert len(loaded) == 87

    row = asdict(spells.get_spell(_SPELL_ID))
    for field in _M33_FIELDS:
        assert field in row
    # story-008: the orphaned per-row level column is gone everywhere (4-field contract).
    assert "level_requirement" not in row


async def test_cast_deducts_focus_and_persists_resonance(reset_db_pool: str) -> None:
    """One cast on real PG: Focus deducts by focus_cost; generated Resonance persists; state derives."""
    pool = await db.get_pool()
    player_id = "cap_cast_single"
    await seed_player_with_pools(pool, player_id=player_id, focus_current=18)
    await spells.load_spells()

    spell = spells.get_spell(_SPELL_ID)
    # Cast reads the catalog's designed value (decision resonance-by-source-ssot), not the
    # source*focus formula — they coincide for arcane_fireball (3) but the catalog is the SSOT.
    expected_gen = spell.resonance_by_source[spell.source]
    assert expected_gen > 0  # not a cantrip — a real Resonance accrual

    await _cast_spell_impl(_make_ctx(player_id), _SPELL_ID)

    assert await _focus_current(player_id) == 18 - spell.focus_cost
    persisted = await db_mutations_resonance.read_player_resonance(player_id, conn=pool)
    assert persisted == {"current": expected_gen, "state": resonance.get_resonance_state(expected_gen)}


async def test_repeated_casts_cross_resonance_bands(reset_db_pool: str) -> None:
    """E2E: seed -> load -> cast x3 -> re-read. Focus, Resonance value, and derived state stay consistent across bands."""
    pool = await db.get_pool()
    player_id = "cap_cast_bands"
    await seed_player_with_pools(pool, player_id=player_id, focus_current=18)
    await spells.load_spells()

    spell = spells.get_spell(_SPELL_ID)
    # Cast reads the catalog's designed resonance (decision resonance-by-source-ssot). The
    # band-walk below assumes a 3-Resonance accrual (3 -> 6 -> 9); guard it so a catalog
    # re-tune of arcane_fireball fails here with a clear cause, not a band mismatch.
    gen = spell.resonance_by_source[spell.source]
    assert gen == 3

    ctx = _make_ctx(player_id)  # one session -> resonance accumulates in-memory + persists
    focus_left = 18
    total = 0
    observed_states = []
    for _ in range(3):
        await _cast_spell_impl(ctx, _SPELL_ID)
        focus_left -= spell.focus_cost
        total += gen
        # Focus deducted on real PG.
        assert await _focus_current(player_id) == focus_left
        # Resonance value persisted + round-trips, state derived from the persisted value.
        got = await db_mutations_resonance.read_player_resonance(player_id, conn=pool)
        assert got["current"] == total
        assert got["state"] == resonance.get_resonance_state(total)
        observed_states.append(got["state"])

    # Walked the full spec band ladder end-to-end.
    assert observed_states == ["stable", "flickering", "overreach"]
