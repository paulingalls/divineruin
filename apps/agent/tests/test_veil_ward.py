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

from datetime import UTC, datetime, timedelta

import pytest

import veil_ward
from session_data import VeilWardState
from veil_ward import WardDuration, WardDurationKind

# --- WardDuration: legal construction of each kind (story-002) ----------------


def test_ward_duration_encounter():
    duration = WardDuration(WardDurationKind.ENCOUNTER)
    assert duration.rounds is None
    assert duration.seconds is None


def test_ward_duration_permanent():
    duration = WardDuration(WardDurationKind.PERMANENT)
    assert duration.rounds is None
    assert duration.seconds is None


def test_ward_duration_rounds():
    duration = WardDuration(WardDurationKind.ROUNDS, rounds=3)
    assert duration.rounds == 3


def test_ward_duration_real_time():
    duration = WardDuration(WardDurationKind.REAL_TIME, seconds=3600)
    assert duration.seconds == 3600


@pytest.mark.parametrize(
    "kind,rounds,seconds",
    [
        (WardDurationKind.ROUNDS, None, None),  # ROUNDS w/o rounds
        (WardDurationKind.ROUNDS, 0, None),  # ROUNDS rounds<=0
        (WardDurationKind.ROUNDS, -1, None),
        (WardDurationKind.REAL_TIME, None, None),  # REAL_TIME w/o seconds
        (WardDurationKind.REAL_TIME, None, 0),  # REAL_TIME seconds<=0
        (WardDurationKind.REAL_TIME, None, -1),
        (WardDurationKind.ENCOUNTER, 3, None),  # ENCOUNTER carrying rounds
        (WardDurationKind.PERMANENT, None, 3600),  # PERMANENT carrying seconds
    ],
)
def test_ward_duration_fails_loud_on_malformed_combos(kind, rounds, seconds):
    with pytest.raises(ValueError):
        WardDuration(kind, rounds=rounds, seconds=seconds)


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


def test_ward_sources_table_has_exactly_three_keys():
    assert set(veil_ward.WARD_SOURCES.keys()) == {"cleric", "druid", "paladin"}


# --- WARD_SOURCES: per-archetype duration + tool_raisable (story-002) ---------


@pytest.mark.parametrize(
    "archetype,kind,rounds",
    [
        ("cleric", WardDurationKind.ENCOUNTER, None),
        ("druid", WardDurationKind.ENCOUNTER, None),
        ("paladin", WardDurationKind.ROUNDS, 3),
    ],
)
def test_ward_sources_durations(archetype, kind, rounds):
    source = veil_ward.WARD_SOURCES[archetype]
    assert source.duration.kind == kind
    assert source.duration.rounds == rounds


@pytest.mark.parametrize("archetype", ["cleric", "druid", "paladin"])
def test_ward_sources_tool_raisable(archetype):
    assert veil_ward.WARD_SOURCES[archetype].tool_raisable is True


# --- tick_ward_rounds: decrement, floor at 0, None passthrough (story-002) ----


def test_tick_ward_rounds_none_passes_through():
    assert veil_ward.tick_ward_rounds(None) is None


@pytest.mark.parametrize(
    "rounds_remaining,expected",
    [
        (3, 2),
        (1, 0),
        (0, 0),  # floored at 0, doesn't go negative
    ],
)
def test_tick_ward_rounds_decrements_and_floors(rounds_remaining, expected):
    assert veil_ward.tick_ward_rounds(rounds_remaining) == expected


def test_tick_ward_rounds_fails_loud_on_negative():
    with pytest.raises(ValueError):
        veil_ward.tick_ward_rounds(-1)


# --- ward_rounds_expired (story-002) ------------------------------------------


def test_ward_rounds_expired_none_never_expires():
    assert veil_ward.ward_rounds_expired(None) is False


@pytest.mark.parametrize(
    "rounds_remaining,expected",
    [
        (1, False),
        (0, True),
        (-1, True),
    ],
)
def test_ward_rounds_expired(rounds_remaining, expected):
    assert veil_ward.ward_rounds_expired(rounds_remaining) == expected


# --- location_expires_at (story-002) -------------------------------------------

_NOW = datetime(2026, 7, 8, 12, 0, 0, tzinfo=UTC)


def test_location_expires_at_permanent_is_none():
    assert veil_ward.location_expires_at(WardDuration(WardDurationKind.PERMANENT), _NOW) is None


def test_location_expires_at_encounter_is_none():
    assert veil_ward.location_expires_at(WardDuration(WardDurationKind.ENCOUNTER), _NOW) is None


def test_location_expires_at_real_time_offsets_now():
    duration = WardDuration(WardDurationKind.REAL_TIME, seconds=3600)
    assert veil_ward.location_expires_at(duration, _NOW) == _NOW + timedelta(seconds=3600)


def test_location_expires_at_rounds_raises():
    duration = WardDuration(WardDurationKind.ROUNDS, rounds=3)
    with pytest.raises(ValueError):
        veil_ward.location_expires_at(duration, _NOW)


def test_location_expires_at_fails_loud_on_naive_now():
    duration = WardDuration(WardDurationKind.PERMANENT)
    with pytest.raises(ValueError):
        veil_ward.location_expires_at(duration, datetime(2026, 7, 8, 12, 0, 0))


# --- location_ward_expired (story-002) -----------------------------------------


def test_location_ward_expired_none_is_permanent_never_expires():
    assert veil_ward.location_ward_expired(None, _NOW) is False


def test_location_ward_expired_boundary_equal_is_expired():
    assert veil_ward.location_ward_expired(_NOW, _NOW) is True


def test_location_ward_expired_future_not_expired():
    assert veil_ward.location_ward_expired(_NOW + timedelta(seconds=1), _NOW) is False


def test_location_ward_expired_past_is_expired():
    assert veil_ward.location_ward_expired(_NOW - timedelta(seconds=1), _NOW) is True


def test_location_ward_expired_fails_loud_on_naive_now():
    with pytest.raises(ValueError):
        veil_ward.location_ward_expired(None, datetime(2026, 7, 8, 12, 0, 0))


def test_location_ward_expired_fails_loud_on_naive_expires_at():
    with pytest.raises(ValueError):
        veil_ward.location_ward_expired(datetime(2026, 7, 8, 12, 0, 0), _NOW)


# --- regression pin: effect constants + halve_generation unchanged (story-002) -


def test_ward_effect_constants_unchanged_by_m24():
    assert veil_ward.WARD_ECHO_BONUS == 4
    assert veil_ward.WARD_DAMAGE_DIE_PENALTY == -1
    assert veil_ward.WARD_DC_PENALTY == -1


@pytest.mark.parametrize(
    "generated,expected",
    [(5, 2), (4, 2), (1, 0), (0, 0), (10, 5), (7, 3)],
)
def test_halve_generation_unchanged_by_m24(generated, expected):
    assert veil_ward.halve_generation(generated) == expected


# --- VeilWardState in-memory defaults ----------------------------------------


def test_veil_ward_state_defaults_inactive():
    state = VeilWardState()
    assert state.active is False
    assert state.source is None
