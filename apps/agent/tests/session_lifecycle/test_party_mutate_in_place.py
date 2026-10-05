"""Replacing Party.members would strand references captured by combat and sibling members."""

from caster_state import ConcentrationState, ResonanceTrack
from party_state import PartyMember
from session_data import SessionData


def _fresh_session():
    return SessionData(player_id="p1", location_id="loc", patron_id="kaelen")


def test_corruption_level_setter_mutates_in_place():
    session = _fresh_session()
    party_id, members_id = id(session.party), id(session.party.members)

    session.corruption_level = 3

    assert id(session.party) == party_id
    assert id(session.party.members) == members_id
    assert session.party.primary.corruption_level == 3


def test_patron_id_setter_mutates_in_place():
    session = _fresh_session()
    party_id, members_id = id(session.party), id(session.party.members)

    session.patron_id = "syrath"

    assert id(session.party) == party_id
    assert id(session.party.members) == members_id
    assert session.party.primary.patron_id == "syrath"


def test_resonance_in_place_mutation_keeps_party_stable():
    session = _fresh_session()
    party_id, members_id = id(session.party), id(session.party.members)

    session.resonance.current = 7
    session.concentration.spell_id = "spell_x"

    assert id(session.party) == party_id
    assert id(session.party.members) == members_id


def test_appending_a_joining_member_mutates_members_in_place():
    """A reference captured before the join must see the appended member."""
    session = _fresh_session()
    party_id, members_id = id(session.party), id(session.party.members)
    members_ref = session.party.members

    session.party.members.append(
        PartyMember(
            player_id="p2",
            resonance=ResonanceTrack(),
            concentration=ConcentrationState(),
        )
    )

    assert id(session.party) == party_id
    assert id(session.party.members) == members_id
    assert members_ref is session.party.members  # the captured reference sees the append
    assert session.party.member_ids == ["p1", "p2"]
