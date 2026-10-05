"""Ward modifiers and source costs are deterministic code constants rather than DB-loaded content."""

from datetime import UTC, datetime, timedelta

import pytest

import veil_ward
from veil_ward import WardDuration, WardDurationKind, WardScope, WardScopeKind


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


def test_ward_modifier_constants():
    assert veil_ward.WARD_ECHO_BONUS == 4
    assert veil_ward.WARD_DAMAGE_DIE_PENALTY == -1
    assert veil_ward.WARD_DC_PENALTY == -1


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
    assert source.min_level == 0


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


def test_ward_scope_kinds():
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
    a = WardScope.location("thornwatch_keep")
    b = WardScope.location("thornwatch_keep")
    assert a == b
    assert hash(a) == hash(b)
    assert len({a, b}) == 1


def test_ward_scope_kind_participates_in_identity():
    assert WardScope.location("x") != WardScope.encounter("x")


@pytest.mark.parametrize("bad_id", ["", None])
def test_ward_scope_fails_loud_on_empty_id(bad_id):
    """An empty scope id can silently resolve the wrong rows as unwarded."""
    with pytest.raises(ValueError):
        WardScope.location(bad_id)
    with pytest.raises(ValueError):
        WardScope.encounter(bad_id)


class TestVeilAnchors:
    """The large anchor is permanent, so its duration cannot come from the timed Artificer source.
    Consumption exists only in item effect prose and is translated by this table."""

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
        source = veil_ward.WARD_SOURCES["artificer"]
        assert source.duration.kind is veil_ward.WardDurationKind.REAL_TIME
        assert source.duration.seconds == 3600
        assert source.tool_raisable is False
