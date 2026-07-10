"""Tests for the pure Veil Ward effects + source table (story-002, M3.2).

A Veil Ward locally reinforces the Veil: while active it halves the Resonance a cast
generates, grants +4 to Hollow Echo rolls, and applies -1 damage die / -1 DC (spec
magic.md:189-217). Like the Resonance and Hollow Echo engines this is a closed-table
deterministic mechanic (CLAUDE.md golden rule #3) — the modifier values and the
per-archetype ward-source costs are code constants, not DB-loaded content. No IO, so
these are plain unit tests with no fixtures or pool.

The activation tool (story-003) and the cast-time halving (story-004) consume these
primitives; the persisted ward state lives in db_mutations_veil_ward (the veil_wards table)
and on CombatState for the encounter scope.

Spec source: docs/game_mechanics/game_mechanics_magic.md §Veil Ward (189-217):
generation halved (round down), +4 echo bonus, -1 damage die, -1 DC; sources
Cleric L7 4F / Druid L9 5F (natural terrain only) / Paladin L10 3F+3S.
"""

from datetime import UTC, datetime, timedelta

import pytest

import veil_ward
from veil_ward import WardDuration, WardDurationKind, WardScope, WardScopeKind

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


@pytest.mark.parametrize("archetype", ["mage", "warrior", "rogue", "bard"])
def test_non_ward_archetypes_absent_from_table(archetype):
    # A class with no ward source at all. Artificer IS in the table (story-005) but is
    # refused by the tool on tool_raisable, not by absence — see the tool's own suite.
    assert archetype not in veil_ward.WARD_SOURCES


def test_ward_sources_table_has_exactly_five_keys():
    assert set(veil_ward.WARD_SOURCES.keys()) == {
        "cleric",
        "druid",
        "paladin",
        "artificer",
        "sacred_site",
    }


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


# --- The two non-tool sources (story-005) -------------------------------------
#
# Both exist so the crafted anchor (story-007) and Phase-11 world entities have a modeled
# source. Neither may be raised through the DM tool: the Artificer's ward is bought with a
# crafted item, and a Sacred site is a property of the world, not an action.


@pytest.mark.parametrize("archetype", ["artificer", "sacred_site"])
def test_non_tool_sources_are_not_tool_raisable(archetype):
    # The load-bearing pin. Artificer is a real playable class costing 0 Focus/0 Stamina —
    # were it tool_raisable, any L7 artificer could raise a free ward through activate_veil_ward.
    assert veil_ward.WARD_SOURCES[archetype].tool_raisable is False


def test_artificer_source_is_a_one_hour_placed_object():
    source = veil_ward.WARD_SOURCES["artificer"]
    assert source.min_level == 7
    assert source.focus == 0
    assert source.stamina == 0
    assert source.duration == WardDuration(WardDurationKind.REAL_TIME, seconds=3600)


def test_sacred_site_source_is_a_free_permanent_hook():
    source = veil_ward.WARD_SOURCES["sacred_site"]
    assert source.focus == 0
    assert source.stamina == 0
    assert source.duration == WardDuration(WardDurationKind.PERMANENT)
    # Never a player class, so the level gate can never fire on it.
    assert source.min_level == 0


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


# location_ward_expired's tests lived here. The function had no production caller -- lazy expiry is
# enforced in read_active_ward's WHERE clause -- so these pinned a rule nothing consulted. Removed
# with it; tests/test_db_mutations_veil_ward_db.py proves expiry against the real SQL predicate.


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


# --- WardScope: a ward is owned by a scope, never by a caster (story-003) -----


def test_ward_scope_kinds():
    """Exactly two scope kinds; their values are the strings persisted in veil_wards.scope_kind."""
    assert WardScopeKind.ENCOUNTER == "encounter"
    assert WardScopeKind.LOCATION == "location"
    assert len(list(WardScopeKind)) == 2


def test_ward_scope_location_constructor():
    scope = WardScope.location("thornwatch_keep")
    assert scope.kind is WardScopeKind.LOCATION
    assert scope.id == "thornwatch_keep"


def test_ward_scope_encounter_constructor():
    scope = WardScope.encounter("combat_42")
    assert scope.kind is WardScopeKind.ENCOUNTER
    assert scope.id == "combat_42"


def test_ward_scope_is_frozen():
    scope = WardScope.location("thornwatch_keep")
    with pytest.raises(AttributeError):
        scope.id = "elsewhere"  # type: ignore[misc]


def test_ward_scope_equality_and_hash():
    """Value semantics: two scopes naming the same place are the same scope."""
    a = WardScope.location("thornwatch_keep")
    b = WardScope.location("thornwatch_keep")
    assert a == b
    assert hash(a) == hash(b)
    assert len({a, b}) == 1


def test_ward_scope_kind_participates_in_identity():
    """A location and an encounter that share an id are NOT the same scope."""
    assert WardScope.location("x") != WardScope.encounter("x")


@pytest.mark.parametrize("bad_id", ["", None])
def test_ward_scope_fails_loud_on_empty_id(bad_id):
    """A scope with no id would silently read/write the wrong rows — fail at construction.

    Guards the cut-over sites, where a null session.location_id would otherwise build a
    malformed scope and quietly return "unwarded" forever.
    """
    with pytest.raises(ValueError):
        WardScope.location(bad_id)
    with pytest.raises(ValueError):
        WardScope.encounter(bad_id)


# --- VEIL_ANCHORS: what kind of ward each crafted anchor makes (story-012) -----


class TestVeilAnchors:
    """The item -> ward join. Both anchors are sourced to the artificer; their DURATIONS differ.

    WARD_SOURCES["artificer"] carries exactly one duration, REAL_TIME 3600s, and that is the SMALL
    anchor's hour. The large anchor is permanent, so its duration cannot come from the source row —
    location_expires_at on REAL_TIME returns an hour from now, never None. It comes from here.

    "consumed on use" / "not consumed" lives only in each item's free-text effects[].description in
    content/items.json; there is no consumable field. This table is where that contract becomes data.
    """

    def test_both_anchors_are_sourced_to_the_artificer(self):
        assert veil_ward.ANCHOR_SOURCE == "artificer"
        assert veil_ward.ANCHOR_SOURCE in veil_ward.WARD_SOURCES

    def test_small_anchor_wards_for_one_hour_and_is_consumed(self):
        anchor = veil_ward.VEIL_ANCHORS["veil_ward_anchor_small"]
        assert anchor.duration.kind is veil_ward.WardDurationKind.REAL_TIME
        assert anchor.duration.seconds == 3600
        assert anchor.consumed is True
        assert anchor.dismissible is True

    def test_large_anchor_is_permanent_undismissible_and_not_consumed(self):
        anchor = veil_ward.VEIL_ANCHORS["veil_ward_anchor_large"]
        assert anchor.duration.kind is veil_ward.WardDurationKind.PERMANENT
        assert anchor.consumed is False
        # dismiss_ward's DELETE carries `AND dismissible`, so False is what makes it unremovable.
        assert anchor.dismissible is False

    def test_small_anchor_expiry_is_an_hour_out_large_anchor_has_none(self):
        # The whole reason duration lives on the anchor: location_expires_at fed the artificer
        # SOURCE duration would hand the large anchor a 1-hour clock instead of a permanent row.
        now = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)
        small = veil_ward.VEIL_ANCHORS["veil_ward_anchor_small"]
        large = veil_ward.VEIL_ANCHORS["veil_ward_anchor_large"]
        assert veil_ward.location_expires_at(small.duration, now) == now + timedelta(hours=1)
        assert veil_ward.location_expires_at(large.duration, now) is None

    def test_the_artificer_source_row_still_carries_the_small_anchors_hour(self):
        # Unchanged by this story; test_recipes_ward_anchor pins it to the item's "1 hour" prose.
        source = veil_ward.WARD_SOURCES["artificer"]
        assert source.duration.kind is veil_ward.WardDurationKind.REAL_TIME
        assert source.duration.seconds == 3600
        assert source.tool_raisable is False
