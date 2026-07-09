"""Tests for SessionData's delegation to a PartyState backing store (story-002).

Covers solo parity (session.resonance/concentration/corruption_level/patron_id
all resolve through party.primary, byte-for-byte identical to pre-refactor behavior),
in-place mutation propagation, and 2-member independence.
"""

from caster_state import ConcentrationState, ResonanceTrack
from party_state import PartyMember, PartyState
from session_data import CombatState, CreationState, SessionData


def test_solo_parity_defaults():
    session = SessionData(player_id="p1", location_id="loc")

    assert session.party.member_ids == ["p1"]
    assert session.resonance == ResonanceTrack()
    assert session.concentration == ConcentrationState()
    assert session.corruption_level == 0
    assert session.patron_id == "none"


def test_player_id_resolves_through_party_primary():
    session = SessionData(player_id="p1", location_id="loc")

    assert session.player_id == "p1"
    assert session.player_id == session.party.primary.player_id


def test_resonance_in_place_mutation_propagates():
    session = SessionData(player_id="p1", location_id="loc")

    r = session.resonance
    r.current = 7

    assert session.resonance.current == 7
    assert session.party.primary.resonance is r


def test_concentration_in_place_mutation_propagates():
    session = SessionData(player_id="p1", location_id="loc")

    c = session.concentration
    c.spell_id = "test-spell"

    assert session.concentration.spell_id == "test-spell"
    assert session.party.primary.concentration is c


def test_corruption_level_setter_round_trips_through_party():
    session = SessionData(player_id="p1", location_id="loc")

    session.corruption_level += 1

    assert session.corruption_level == 1
    assert session.party.primary.corruption_level == 1


def test_patron_id_construction_and_setter_drift_guard():
    session = SessionData(player_id="p1", location_id="loc", patron_id="kaelen")

    assert session.patron_id == "kaelen"
    assert session.party.primary.patron_id == "kaelen"

    session.patron_id = "syrath"

    assert session.patron_id == "syrath"
    assert session.party.primary.patron_id == "syrath"


def test_two_member_party_independence():
    session = SessionData(player_id="p1", location_id="loc")
    session.party = PartyState(
        members=[
            session.party.primary,
            PartyMember(
                player_id="p2",
                resonance=ResonanceTrack(),
                concentration=ConcentrationState(),
            ),
        ]
    )

    p2 = session.party.member("p2")
    assert p2 is not None
    p2.resonance.current = 5
    p2.concentration.spell_id = "p2-spell"

    p1 = session.party.member("p1")
    assert p1 is not None
    assert p1.resonance.current == 0
    assert p1.concentration.spell_id is None
    assert session.resonance.current == 0
    assert session.resonance is p1.resonance


def test_construction_smoke_prod_kwarg_shapes():
    session_a = SessionData(player_id="p", location_id="", room=None, creation_state=CreationState())
    assert session_a.player_id == "p"

    session_b = SessionData(player_id="p", location_id="loc", room=None, patron_id="god")
    assert session_b.player_id == "p"
    assert session_b.patron_id == "god"


def test_player_id_has_no_setter():
    session = SessionData(player_id="p1", location_id="loc")

    try:
        session.player_id = "x"
    except AttributeError:
        pass
    else:
        raise AssertionError("expected AttributeError when setting player_id")


# --- SessionData.location_ward: a HUD mirror with no correctness consumer (story-004) --------


def test_location_ward_defaults_to_none():
    """A fresh session mirrors no ward until hydration reads one."""
    assert SessionData(player_id="p1", location_id="loc").location_ward is None


def test_location_ward_is_a_plain_mirror_not_a_resolver():
    """It stores what the last read returned. It does NOT consult combat_state.

    Resolution lives in exactly one place — ward_resolution.resolve_scope_ward — because a
    synchronous property here could not await the DB, and would go stale the moment a ward's
    expires_at lapsed: reporting warded while the cast path correctly reads unwarded.
    """
    session = SessionData(player_id="p1", location_id="loc")
    session.location_ward = {"source": "cleric", "expires_at": None, "dismissible": True}

    assert session.location_ward["source"] == "cleric"
    # No resolution accessor exists on the session — the mirror is not an authority.
    assert not hasattr(session, "scope_ward")


def test_location_ward_is_not_shadowed_by_an_encounter_ward():
    """Setting a combat ward does not touch the location mirror; they are distinct scopes."""
    session = SessionData(player_id="p1", location_id="loc")
    session.combat_state = _combat_state(veil_ward={"source": "paladin", "rounds_remaining": 3})

    assert session.location_ward is None


# --- CombatState.veil_ward: the encounter ward rides the combat row (story-004, M24) ---------


def _combat_state(**kwargs) -> CombatState:
    return CombatState(combat_id="c1", participants=[], initiative_order=[], **kwargs)


def test_combat_state_starts_unwarded():
    """No ward until one is raised. None means absence, never a default-inactive placeholder."""
    assert _combat_state().veil_ward is None


def test_encounter_ward_round_trips_through_to_dict_from_dict():
    """AC2: the encounter ward survives the trip through combat_instances.data JSONB.

    A plain dict, mirroring CombatParticipant.conditions — JSONB-native, so asdict() serializes it
    and from_dict passes it straight back.
    """
    ward = {"source": "paladin", "rounds_remaining": 3}
    state = _combat_state(veil_ward=ward)

    rebuilt = CombatState.from_dict(state.to_dict())

    assert rebuilt.veil_ward is not None
    assert rebuilt.veil_ward == ward
    assert rebuilt.veil_ward["rounds_remaining"] == 3  # story-006 ticks this at the WRAP beat


def test_encounter_ward_with_no_round_clock_round_trips():
    """An ENCOUNTER-duration ward carries rounds_remaining None — it dies with the combat row."""
    state = _combat_state(veil_ward={"source": "cleric", "rounds_remaining": None})
    assert CombatState.from_dict(state.to_dict()).veil_ward == {"source": "cleric", "rounds_remaining": None}


def test_legacy_row_without_veil_ward_field_falls_back_to_none():
    """A combat row written before story-004 carries no veil_ward key and must still load."""
    data = _combat_state().to_dict()
    data.pop("veil_ward")
    assert CombatState.from_dict(data).veil_ward is None
