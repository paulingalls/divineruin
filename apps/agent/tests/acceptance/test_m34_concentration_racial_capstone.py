"""Capstone: M3.4 Concentration + Racial Resonance end-to-end against a real Postgres testcontainer.

stories 001-006 shipped the M3.4 seam with unit / mock-conn coverage: the racial bonus table +
loader (001), concentration engine + persistence (002), the resonance / hollow_echo helpers
(003/004), the Draethar inner_fire tool (005), and the cast keystone that composes them (006).
This capstone proves they COMPOSE against ONE seeded testcontainer (auto-marked `acceptance` by
tests/acceptance/conftest.py), catching the loader / JSONB-persistence seams the mocked units
can't:

- A Korath's primal cast applies the racial -1 to the Resonance that persists into players.data.
- Casting a concentration spell, then a second, leaves the SECOND as the single active
  concentration in players.data (the first ended) — single-slot overwrite, persisted.
- get_racial_resonance_modifier reads the real seeded racial_resonance_bonuses table (the DB
  loader, not the JSON fixture) and returns every spec value for all six races.
- A Draethar reaching Overreach then using inner_fire drops persisted Resonance by 3, composing
  with the persisted concentration without error.

Each test uses a distinct player_id since the testcontainer DB is shared across the session.
cast_spell gates ONLY Focus (story-004), so a Focus-funded player casts any spell id; the racial
branch keys on players.data race, seeded per test.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from acceptance.seeds import seed_player_with_pools

import db
import db_mutations_concentration
import db_mutations_resonance
import db_queries
import racial_resonance
import spells
from draethar_inner_fire import _inner_fire_impl
from session_data import CombatParticipant, CombatState, SessionData
from spell_casting import _cast_spell_impl


def _make_ctx(player_id: str) -> MagicMock:
    """A RunContext whose userdata is a real SessionData (room=None -> event bus only)."""
    ctx = MagicMock()
    ctx.userdata = SessionData(player_id=player_id, location_id="accord_guild_hall", room=None)
    return ctx


async def _set_race(pool, player_id: str, race: str) -> None:
    """Set players.data race the cast path reads (seed_player_with_pools leaves it unset)."""
    await pool.execute(
        "UPDATE players SET data = jsonb_set(data, '{race}', $2::jsonb) WHERE player_id = $1",
        player_id,
        json.dumps(race),
    )


async def _hp_current(player_id: str) -> int:
    """Read the persisted HP back from players.data JSONB on real PG."""
    player = await db_queries.get_player(player_id, conn=await db.get_pool())
    assert player is not None
    return player["hp"]["current"]


async def test_korath_primal_reduction_persists(reset_db_pool: str) -> None:
    """A Korath's primal cast applies the racial -1 to the generated Resonance, and the reduced
    value (not the unreduced baseline) is what persists into players.data (AC1)."""
    pool = await db.get_pool()
    player_id = "cap_m34_korath_primal"
    await seed_player_with_pools(pool, player_id=player_id, focus_current=18)
    await _set_race(pool, player_id, "korath")
    await spells.load_spells()
    await racial_resonance.load_racial_resonance()  # racial table FROM THE DB, not the JSON fixture

    # primal_ice_storm: source primal, resonance_by_source.primal 2 -> Korath -1 -> 1 (floor 0).
    spell = spells.get_spell("primal_ice_storm")
    base = spell.resonance_by_source[spell.source]
    assert base == 2  # the reduction is observable: 2 -> 1, not 1 -> 0

    packet = json.loads(await _cast_spell_impl(_make_ctx(player_id), "primal_ice_storm"))
    assert packet["resonance_generated"] == base - 1  # 1

    # The reduced 1, not the unreduced baseline 2, is what persisted (a non-Korath would persist 2).
    persisted = await db_mutations_resonance.read_player_resonance(player_id, conn=pool)
    assert persisted["current"] == 1


async def test_second_concentration_cast_replaces_the_first(reset_db_pool: str) -> None:
    """Casting a concentration spell, then a second, leaves the SECOND as the single active
    concentration in players.data — the first ended (single-slot overwrite, persisted) (AC2)."""
    pool = await db.get_pool()
    player_id = "cap_m34_concentration"
    await seed_player_with_pools(pool, player_id=player_id, focus_current=18)
    await spells.load_spells()

    ctx = _make_ctx(player_id)  # one session -> concentration carried across casts

    await _cast_spell_impl(ctx, "arcane_fly")  # concentration spell, focus 3
    first = await db_mutations_concentration.read_player_concentration(player_id, conn=pool)
    assert first["spell_id"] == "arcane_fly"

    await _cast_spell_impl(ctx, "arcane_invisibility")  # second concentration spell, focus 3
    second = await db_mutations_concentration.read_player_concentration(player_id, conn=pool)
    assert second["spell_id"] == "arcane_invisibility"  # the first ended; one active concentration
    assert ctx.userdata.concentration.spell_id == "arcane_invisibility"


async def test_racial_table_loads_every_race_from_db(reset_db_pool: str) -> None:
    """The DB loader populates get_racial_resonance_modifier from the seeded
    racial_resonance_bonuses table, returning every spec value for all six races (AC3)."""
    await racial_resonance.load_racial_resonance()  # read the table FROM THE DB (not a fixture)

    get = racial_resonance.get_racial_resonance_modifier
    assert get("human", "decay_bonus") == 1
    assert get("korath", "primal_reduction") == 1
    assert get("thessyn", "flickering_threshold_bonus") == 1
    assert get("vaelti", "echo_save_advantage") is True
    assert get("draethar", "inner_fire_resonance_reduction") == 3
    assert get("draethar", "inner_fire_self_damage") == "1d6"
    assert get("elari", "veil_sense") is True
    assert get("elari", "resonance_arcana_bonus") == 1


async def test_draethar_inner_fire_after_overreach_cast_composes(reset_db_pool: str) -> None:
    """A Draethar casts a concentration spell into Overreach, then uses inner_fire: persisted
    Resonance drops by 3 and composes with the persisted concentration without error (AC4 E2E)."""
    pool = await db.get_pool()
    player_id = "cap_m34_draethar"
    await seed_player_with_pools(pool, player_id=player_id, focus_current=18)
    await _set_race(pool, player_id, "draethar")
    await spells.load_spells()
    await racial_resonance.load_racial_resonance()

    ctx = _make_ctx(player_id)
    # Seed prior accrual: a single concentration cast can't reach Overreach from 0 (max
    # concentration generation is 4), so start at 7 — +2 from the cast lands exactly at 9.
    ctx.userdata.resonance.current = 7
    ctx.userdata.combat_state = CombatState(
        combat_id="cap_m34_combat",
        participants=[
            CombatParticipant(id=player_id, name="Pyre", type="player", initiative=14, hp_current=28, hp_max=28, ac=14),
            CombatParticipant(id="hollow_1", name="Hollow", type="enemy", initiative=8, hp_current=9, hp_max=9, ac=12),
        ],
        initiative_order=[player_id, "hollow_1"],
    )

    # Cast arcane_invisibility (concentration, +2): 7 -> 9 = Overreach (the echo auto-rolls).
    cast = json.loads(await _cast_spell_impl(ctx, "arcane_invisibility"))
    assert cast["state"] == "overreach"
    assert (await db_mutations_resonance.read_player_resonance(player_id, conn=pool))["current"] == 9
    assert (await db_mutations_concentration.read_player_concentration(player_id, conn=pool))["spell_id"] == (
        "arcane_invisibility"
    )

    # inner_fire (real dice): drop Resonance by 3 (9 -> 6) and take 1d6 self fire damage.
    fire = json.loads(await _inner_fire_impl(ctx))
    assert fire["resonance_reduced"] == 3
    assert 1 <= fire["fire_damage"] <= 6  # 1d6 self damage — a dice-expr regression (e.g. 2d6) trips here
    assert (await db_mutations_resonance.read_player_resonance(player_id, conn=pool))["current"] == 6
    # Participant (28) syncs from the seeded pool, so the persisted hp is source-agnostic: 28 - rolled.
    assert await _hp_current(player_id) == 28 - fire["fire_damage"]
    # Concentration survives the inner_fire — the composed state is intact.
    assert (await db_mutations_concentration.read_player_concentration(player_id, conn=pool))["spell_id"] == (
        "arcane_invisibility"
    )
