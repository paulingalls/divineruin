"""Tests for SessionData's delegation to a PartyState backing store (story-002).

Covers solo parity (session.resonance/veil_ward/concentration/corruption_level/patron_id
all resolve through party.primary, byte-for-byte identical to pre-refactor behavior),
in-place mutation propagation, and 2-member independence.
"""

from caster_state import ConcentrationState, ResonanceTrack, VeilWardState
from party_state import PartyMember, PartyState
from session_data import CreationState, SessionData


def test_solo_parity_defaults():
    session = SessionData(player_id="p1", location_id="loc")

    assert session.party.member_ids == ["p1"]
    assert session.resonance == ResonanceTrack()
    assert session.veil_ward == VeilWardState()
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


def test_veil_ward_in_place_mutation_propagates():
    session = SessionData(player_id="p1", location_id="loc")

    vw = session.veil_ward
    vw.active = True
    vw.source = "test-source"

    assert session.veil_ward.active is True
    assert session.veil_ward.source == "test-source"
    assert session.party.primary.veil_ward is vw


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
                veil_ward=VeilWardState(),
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
