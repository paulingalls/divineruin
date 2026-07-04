"""Guard the Party.members mutate-in-place invariant (constraint f4f16c93076e,
decision ce6ca819008c).

Per-member state on SessionData reaches ONE backing store — session.party.members.
Every per-member write and the live participant-join append must MUTATE that store in
place, never wholesale-reassign session.party or session.party.members. If it did,
already-captured references (e.g. a combat_init loop holding session.party, or a
sibling member reference) would silently point at a stale object.

This suite pins the invariant by identity: writing each per-member facade field and
appending a joining member both keep id(session.party) and id(session.party.members)
stable. The invariant is convention-only today; story-001 is the first story to touch
the party model and adds this guard so a later refactor that reassigns instead of
mutating goes red here.
"""

from caster_state import ConcentrationState, ResonanceTrack, VeilWardState
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
    session.veil_ward.active = True
    session.concentration.spell_id = "spell_x"

    assert id(session.party) == party_id
    assert id(session.party.members) == members_id


def test_appending_a_joining_member_mutates_members_in_place():
    """The live participant-join path appends onto party.members (constraint f4f16c93076e).
    Both the party AND the members list must stay the same objects, so a reference captured
    before the join still sees the new member."""
    session = _fresh_session()
    party_id, members_id = id(session.party), id(session.party.members)
    members_ref = session.party.members

    session.party.members.append(
        PartyMember(
            player_id="p2",
            resonance=ResonanceTrack(),
            veil_ward=VeilWardState(),
            concentration=ConcentrationState(),
        )
    )

    assert id(session.party) == party_id
    assert id(session.party.members) == members_id
    assert members_ref is session.party.members  # the captured reference sees the append
    assert session.party.member_ids == ["p1", "p2"]
