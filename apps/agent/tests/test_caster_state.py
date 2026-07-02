"""Tests for caster state value types (ResonanceTrack, VeilWardState, ConcentrationState)."""

from dataclasses import asdict

import caster_state as caster_state
import session_data as session_data


class TestResonanceTrack:
    def test_resonance_track_defaults(self):
        track = caster_state.ResonanceTrack()
        assert track.current == 0
        assert track.flickering_bonus == 0

    def test_resonance_track_with_values(self):
        track = caster_state.ResonanceTrack(current=5, flickering_bonus=2)
        assert track.current == 5
        assert track.flickering_bonus == 2

    def test_resonance_track_state_property(self):
        track = caster_state.ResonanceTrack(current=0)
        # state property derives from resonance module
        assert track.state is not None

    def test_resonance_track_asdict_roundtrip(self):
        original = caster_state.ResonanceTrack(current=3, flickering_bonus=1)
        d = asdict(original)
        reconstructed = caster_state.ResonanceTrack(**d)
        assert reconstructed.current == original.current
        assert reconstructed.flickering_bonus == original.flickering_bonus

    def test_back_compat_session_data_reexport(self):
        """Back-compat guard: ResonanceTrack imported from session_data is the same class."""
        assert session_data.ResonanceTrack is caster_state.ResonanceTrack


class TestVeilWardState:
    def test_veil_ward_defaults(self):
        ward = caster_state.VeilWardState()
        assert ward.active is False
        assert ward.source is None

    def test_veil_ward_with_values(self):
        ward = caster_state.VeilWardState(active=True, source="archetype_123")
        assert ward.active is True
        assert ward.source == "archetype_123"

    def test_veil_ward_asdict_roundtrip(self):
        original = caster_state.VeilWardState(active=True, source="test")
        d = asdict(original)
        reconstructed = caster_state.VeilWardState(**d)
        assert reconstructed.active == original.active
        assert reconstructed.source == original.source

    def test_back_compat_session_data_reexport(self):
        """Back-compat guard: VeilWardState imported from session_data is the same class."""
        assert session_data.VeilWardState is caster_state.VeilWardState


class TestConcentrationState:
    def test_concentration_defaults(self):
        conc = caster_state.ConcentrationState()
        assert conc.spell_id is None
        assert conc.is_active is False

    def test_concentration_with_spell(self):
        conc = caster_state.ConcentrationState(spell_id="fireball")
        assert conc.spell_id == "fireball"
        assert conc.is_active is True

    def test_concentration_is_active_property(self):
        conc = caster_state.ConcentrationState(spell_id=None)
        assert conc.is_active is False
        conc.spell_id = "magic_missile"
        assert conc.is_active is True

    def test_concentration_asdict_roundtrip(self):
        original = caster_state.ConcentrationState(spell_id="spell_456")
        d = asdict(original)
        reconstructed = caster_state.ConcentrationState(**d)
        assert reconstructed.spell_id == original.spell_id
        assert reconstructed.is_active == original.is_active

    def test_back_compat_session_data_reexport(self):
        """Back-compat guard: ConcentrationState imported from session_data is the same class."""
        assert session_data.ConcentrationState is caster_state.ConcentrationState
