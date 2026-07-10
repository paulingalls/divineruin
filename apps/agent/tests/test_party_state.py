"""Tests for party state module (PartyMember, PartyState)."""

import caster_state
import party_state


class TestPartyMember:
    def test_party_member_defaults(self):
        member = party_state.PartyMember(
            player_id="p1",
            resonance=caster_state.ResonanceTrack(),
            concentration=caster_state.ConcentrationState(),
        )
        assert member.player_id == "p1"
        assert member.corruption_level == 0
        assert member.patron_id == "none"

    def test_party_member_with_custom_values(self):
        member = party_state.PartyMember(
            player_id="p1",
            resonance=caster_state.ResonanceTrack(current=5),
            concentration=caster_state.ConcentrationState(spell_id="fireball"),
            corruption_level=3,
            patron_id="god_123",
        )
        assert member.player_id == "p1"
        assert member.resonance.current == 5
        assert member.concentration.spell_id == "fireball"
        assert member.corruption_level == 3
        assert member.patron_id == "god_123"


class TestPartyStateSolo:
    def test_solo_builds_one_member(self):
        party = party_state.PartyState.solo("player_1")
        assert len(party.members) == 1
        assert party.members[0].player_id == "player_1"

    def test_solo_uses_default_substates(self):
        party = party_state.PartyState.solo("p1")
        member = party.members[0]
        assert member.resonance.current == 0
        assert member.concentration.spell_id is None
        assert member.corruption_level == 0
        assert member.patron_id == "none"

    def test_solo_with_custom_resonance(self):
        res = caster_state.ResonanceTrack(current=5)
        party = party_state.PartyState.solo("p1", resonance=res)
        assert party.members[0].resonance.current == 5

    def test_solo_with_custom_concentration(self):
        conc = caster_state.ConcentrationState(spell_id="spell_123")
        party = party_state.PartyState.solo("p1", concentration=conc)
        assert party.members[0].concentration.spell_id == "spell_123"

    def test_solo_with_corruption_and_patron(self):
        party = party_state.PartyState.solo("p1", corruption_level=2, patron_id="god_456")
        member = party.members[0]
        assert member.corruption_level == 2
        assert member.patron_id == "god_456"


class TestPartyStateMembership:
    def test_member_lookup_hit(self):
        party = party_state.PartyState(
            [
                party_state.PartyMember(
                    player_id="p1",
                    resonance=caster_state.ResonanceTrack(),
                    concentration=caster_state.ConcentrationState(),
                ),
                party_state.PartyMember(
                    player_id="p2",
                    resonance=caster_state.ResonanceTrack(),
                    concentration=caster_state.ConcentrationState(),
                ),
            ]
        )
        member = party.member("p1")
        assert member is not None
        assert member.player_id == "p1"

    def test_member_lookup_miss(self):
        party = party_state.PartyState(
            [
                party_state.PartyMember(
                    player_id="p1",
                    resonance=caster_state.ResonanceTrack(),
                    concentration=caster_state.ConcentrationState(),
                ),
            ]
        )
        member = party.member("p99")
        assert member is None

    def test_contains_true(self):
        party = party_state.PartyState.solo("p1")
        assert party.contains("p1") is True

    def test_contains_false(self):
        party = party_state.PartyState.solo("p1")
        assert party.contains("p2") is False

    def test_member_ids(self):
        p1 = party_state.PartyMember(
            player_id="p1",
            resonance=caster_state.ResonanceTrack(),
            concentration=caster_state.ConcentrationState(),
        )
        p2 = party_state.PartyMember(
            player_id="p2",
            resonance=caster_state.ResonanceTrack(),
            concentration=caster_state.ConcentrationState(),
        )
        party = party_state.PartyState([p1, p2])
        assert party.member_ids == ["p1", "p2"]


class TestPartyStatePrimary:
    def test_primary_returns_first_member(self):
        p1 = party_state.PartyMember(
            player_id="p1",
            resonance=caster_state.ResonanceTrack(),
            concentration=caster_state.ConcentrationState(),
        )
        party = party_state.PartyState([p1])
        assert party.primary is p1
        assert party.primary.player_id == "p1"

    def test_primary_raises_on_empty_party(self):
        party = party_state.PartyState([])
        try:
            _ = party.primary
            raise AssertionError("Should have raised")
        except (ValueError, IndexError):
            pass


class TestPartyStateIsolation:
    def test_per_member_isolation(self):
        """Mutating member B's state does not affect member A."""
        p1 = party_state.PartyMember(
            player_id="p1",
            resonance=caster_state.ResonanceTrack(current=0),
            concentration=caster_state.ConcentrationState(spell_id=None),
        )
        p2 = party_state.PartyMember(
            player_id="p2",
            resonance=caster_state.ResonanceTrack(current=0),
            concentration=caster_state.ConcentrationState(spell_id=None),
        )
        party = party_state.PartyState([p1, p2])

        # Mutate member B
        member_b = party.member("p2")
        assert member_b is not None
        member_b.resonance.current = 5
        member_b.concentration.spell_id = "spell_x"

        # Member A unchanged
        member_a = party.member("p1")
        assert member_a is not None
        assert member_a.resonance.current == 0
        assert member_a.concentration.spell_id is None


class TestPartyStateSerialize:
    def test_to_dict(self):
        party = party_state.PartyState.solo("p1", corruption_level=1)
        d = party.to_dict()
        assert isinstance(d, dict)
        assert "members" in d
        assert len(d["members"]) == 1

    def test_to_dict_member_structure(self):
        party = party_state.PartyState.solo(
            "p1",
            resonance=caster_state.ResonanceTrack(current=3),
            corruption_level=2,
        )
        d = party.to_dict()
        member_dict = d["members"][0]
        assert member_dict["player_id"] == "p1"
        assert member_dict["resonance"]["current"] == 3
        assert member_dict["corruption_level"] == 2

    def test_from_dict_single_member(self):
        data = {
            "members": [
                {
                    "player_id": "p1",
                    "resonance": {"current": 0, "flickering_bonus": 0},
                    "concentration": {"spell_id": None},
                    "corruption_level": 0,
                    "patron_id": "none",
                }
            ]
        }
        party = party_state.PartyState.from_dict(data)
        assert len(party.members) == 1
        assert party.members[0].player_id == "p1"

    def test_from_dict_reconstructs_instances(self):
        """from_dict rebuilds nested value-type INSTANCES, not raw dicts."""
        data = {
            "members": [
                {
                    "player_id": "p1",
                    "resonance": {"current": 5, "flickering_bonus": 1},
                    "concentration": {"spell_id": "spell_123"},
                    "corruption_level": 2,
                    "patron_id": "god_456",
                }
            ]
        }
        party = party_state.PartyState.from_dict(data)
        member = party.members[0]

        # Check that nested fields are INSTANCES, not dicts
        assert isinstance(member.resonance, caster_state.ResonanceTrack)
        assert isinstance(member.concentration, caster_state.ConcentrationState)

        # Check values
        assert member.resonance.current == 5
        assert member.resonance.flickering_bonus == 1
        assert member.concentration.spell_id == "spell_123"

    def test_roundtrip_single_member(self):
        original = party_state.PartyState.solo(
            "p1",
            resonance=caster_state.ResonanceTrack(current=5, flickering_bonus=1),
            concentration=caster_state.ConcentrationState(spell_id="spell_x"),
            corruption_level=2,
            patron_id="god_789",
        )
        d = original.to_dict()
        restored = party_state.PartyState.from_dict(d)

        member_orig = original.members[0]
        member_rest = restored.members[0]

        assert member_rest.player_id == member_orig.player_id
        assert member_rest.resonance.current == member_orig.resonance.current
        assert member_rest.resonance.flickering_bonus == member_orig.resonance.flickering_bonus
        assert member_rest.concentration.spell_id == member_orig.concentration.spell_id
        assert member_rest.corruption_level == member_orig.corruption_level
        assert member_rest.patron_id == member_orig.patron_id

    def test_roundtrip_multiple_members_order(self):
        """Roundtrip preserves member order."""
        p1 = party_state.PartyMember(
            player_id="p1",
            resonance=caster_state.ResonanceTrack(current=1),
            concentration=caster_state.ConcentrationState(),
        )
        p2 = party_state.PartyMember(
            player_id="p2",
            resonance=caster_state.ResonanceTrack(current=2),
            concentration=caster_state.ConcentrationState(),
        )
        original = party_state.PartyState([p1, p2])

        d = original.to_dict()
        restored = party_state.PartyState.from_dict(d)

        assert [m.player_id for m in restored.members] == ["p1", "p2"]
        assert restored.members[0].resonance.current == 1
        assert restored.members[1].resonance.current == 2


class TestPartyMemberWeaponFlags:
    """Per-member weapon-durability flags (M18 story-003): the swing that arms end-of-combat
    durability accrual is recorded on the SWINGING member, not the session, so a non-primary
    member's swings accrue their OWN weapon's durability."""

    def test_weapon_flags_default_false(self):
        member = party_state.PartyMember(
            player_id="p1",
            resonance=caster_state.ResonanceTrack(),
            concentration=caster_state.ConcentrationState(),
        )
        assert member.weapon_used is False
        assert member.weapon_crit_vs_heavy is False

    def test_weapon_flags_custom(self):
        member = party_state.PartyMember(
            player_id="p1",
            resonance=caster_state.ResonanceTrack(),
            concentration=caster_state.ConcentrationState(),
            weapon_used=True,
            weapon_crit_vs_heavy=True,
        )
        assert member.weapon_used is True
        assert member.weapon_crit_vs_heavy is True

    def test_to_dict_includes_weapon_flags(self):
        p = party_state.PartyMember(
            player_id="p1",
            resonance=caster_state.ResonanceTrack(),
            concentration=caster_state.ConcentrationState(),
            weapon_used=True,
            weapon_crit_vs_heavy=True,
        )
        d = party_state.PartyState([p]).to_dict()
        assert d["members"][0]["weapon_used"] is True
        assert d["members"][0]["weapon_crit_vs_heavy"] is True

    def test_roundtrip_weapon_flags(self):
        p = party_state.PartyMember(
            player_id="p1",
            resonance=caster_state.ResonanceTrack(),
            concentration=caster_state.ConcentrationState(),
            weapon_used=True,
            weapon_crit_vs_heavy=True,
        )
        restored = party_state.PartyState.from_dict(party_state.PartyState([p]).to_dict())
        assert restored.members[0].weapon_used is True
        assert restored.members[0].weapon_crit_vs_heavy is True

    def test_from_dict_defaults_weapon_flags_when_absent(self):
        # A party dict persisted before M18 has no weapon flags; from_dict must default them to
        # False rather than KeyError, so old sessions load clean.
        data = {
            "members": [
                {
                    "player_id": "p1",
                    "resonance": {"current": 0, "flickering_bonus": 0},
                    "concentration": {"spell_id": None},
                    "corruption_level": 0,
                    "patron_id": "none",
                }
            ]
        }
        member = party_state.PartyState.from_dict(data).members[0]
        assert member.weapon_used is False
        assert member.weapon_crit_vs_heavy is False
