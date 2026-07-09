"""Unified per-member write contract on SessionData (concern 3ec54e78cae8).

Before this story SessionData exposed per-member state through THREE inconsistent
contracts: resonance/concentration were read-only properties (mutate the
returned object in place), corruption_level was a property + setter, patron_id was a
real field mirrored via __setattr__. This suite pins the unified contract:

  - resonance / concentration / corruption_level are all @property read +
    setter write, each delegating to session.party.primary.<field>.
  - patron_id stays the single documented exception (real dataclass field mirrored via
    __setattr__ so pyright validates the ~120 SessionData(...) construction sites).
  - member_state(player_id) is the sanctioned multi-PC per-member accessor; it fails
    loud on an unknown id.
  - For a solo (1-member) party every facade read/write hits the same object as
    party.primary, so single-player behavior stays byte-identical.
"""

import pytest

from caster_state import ConcentrationState, ResonanceTrack
from party_state import PartyMember
from session_data import SessionData


def _fresh_session():
    return SessionData(player_id="p1", location_id="loc")


# --- Setters delegate to party.primary (the new uniform contract) ---------------------


def test_resonance_setter_delegates_to_primary():
    session = _fresh_session()
    track = ResonanceTrack(current=5, flickering_bonus=1)

    session.resonance = track

    assert session.party.primary.resonance is track
    assert session.resonance is track
    assert session.resonance.current == 5


def test_concentration_setter_delegates_to_primary():
    session = _fresh_session()
    conc = ConcentrationState(spell_id="fireball")

    session.concentration = conc

    assert session.party.primary.concentration is conc
    assert session.concentration.spell_id == "fireball"


def test_setters_mutate_party_in_place():
    """The new setters must reassign primary's field, never replace session.party or its
    members list (constraint f4f16c93076e — same invariant the guard suite pins)."""
    session = _fresh_session()
    party_id, members_id = id(session.party), id(session.party.members)

    session.resonance = ResonanceTrack(current=3)
    session.concentration = ConcentrationState(spell_id="s")

    assert id(session.party) == party_id
    assert id(session.party.members) == members_id


# --- member_state: the sanctioned multi-PC per-member accessor -------------------------


def test_member_state_returns_primary_for_solo():
    session = _fresh_session()

    assert session.member_state("p1") is session.party.primary


def test_member_state_returns_the_named_member_in_a_party():
    session = _fresh_session()
    second = PartyMember(
        player_id="p2",
        resonance=ResonanceTrack(),
        concentration=ConcentrationState(),
    )
    session.party.members.append(second)

    assert session.member_state("p2") is second
    assert session.member_state("p1") is session.party.primary


def test_member_state_fails_loud_on_unknown_id():
    session = _fresh_session()

    with pytest.raises(ValueError):
        session.member_state("nobody")


# --- patron_id: the single documented exception (real field, mirrored) ----------------


def test_patron_id_still_mirrors_via_setattr():
    session = SessionData(player_id="p1", location_id="loc", patron_id="kaelen")
    assert session.patron_id == "kaelen"
    assert session.party.primary.patron_id == "kaelen"

    session.patron_id = "syrath"

    assert session.patron_id == "syrath"
    assert session.party.primary.patron_id == "syrath"


# --- Solo byte-identical: facade reads hit the same object as party.primary ------------


def test_solo_facade_reads_are_the_primary_objects():
    session = _fresh_session()

    assert session.resonance is session.party.primary.resonance
    assert session.concentration is session.party.primary.concentration
    assert session.corruption_level == session.party.primary.corruption_level
    assert session.member_state("p1") is session.party.primary
