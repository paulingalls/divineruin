"""Tests for the pure Veil Ward effects + source table (story-002, M3.2).

A Veil Ward locally reinforces the Veil: while active it halves the Resonance a cast
generates, grants +4 to Hollow Echo rolls, and applies -1 damage die / -1 DC (spec
magic.md:189-217). Like the Resonance and Hollow Echo engines this is a closed-table
deterministic mechanic (CLAUDE.md golden rule #3) — the modifier values and the
per-archetype ward-source costs are code constants, not DB-loaded content. No IO, so
these are plain unit tests with no fixtures or pool.

The activation tool (story-003) and the cast-time halving (story-004) consume these
primitives; the persisted ward state lives in db_mutations_veil_ward + the
VeilWardState session field (tested here for its defaults).

Spec source: docs/game_mechanics/game_mechanics_magic.md §Veil Ward (189-217):
generation halved (round down), +4 echo bonus, -1 damage die, -1 DC; sources
Cleric L7 4F / Druid L9 5F (natural terrain only) / Paladin L10 3F+3S.
"""

import pytest

import veil_ward
from session_data import VeilWardState

# --- halve_generation: round down (spec 197) ---------------------------------


@pytest.mark.parametrize(
    "generated,expected",
    [
        (5, 2),  # 5 // 2
        (4, 2),
        (1, 0),  # round down to nothing
        (0, 0),
        (10, 5),
        (7, 3),
    ],
)
def test_halve_generation_rounds_down(generated, expected):
    assert veil_ward.halve_generation(generated) == expected


def test_halve_generation_fails_loud_on_negative():
    with pytest.raises(ValueError):
        veil_ward.halve_generation(-1)


# --- ward modifier constants (spec 195-200) ----------------------------------


def test_ward_modifier_constants():
    assert veil_ward.WARD_ECHO_BONUS == 4
    assert veil_ward.WARD_DAMAGE_DIE_PENALTY == -1
    assert veil_ward.WARD_DC_PENALTY == -1


# --- WARD_SOURCES: per-archetype level + cost (spec 204-210) ------------------


@pytest.mark.parametrize(
    "archetype,min_level,focus,stamina",
    [
        ("cleric", 7, 4, 0),
        ("druid", 9, 5, 0),
        ("paladin", 10, 3, 3),
    ],
)
def test_ward_sources_costs(archetype, min_level, focus, stamina):
    source = veil_ward.WARD_SOURCES[archetype]
    assert source.min_level == min_level
    assert source.focus == focus
    assert source.stamina == stamina


@pytest.mark.parametrize("archetype", ["mage", "warrior", "rogue", "bard", "artificer"])
def test_non_ward_archetypes_absent_from_table(archetype):
    # Artificer (item) and Sacred-site (passive) sources are deferred past M3.2;
    # only the Focus/Stamina caster sources are in the table.
    assert archetype not in veil_ward.WARD_SOURCES


# --- VeilWardState in-memory defaults ----------------------------------------


def test_veil_ward_state_defaults_inactive():
    state = VeilWardState()
    assert state.active is False
    assert state.source is None
