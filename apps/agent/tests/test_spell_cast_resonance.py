"""Resonance generation on a cast — catalog-over-formula sourcing and the racial modifiers (fixtures: _spell_casting_helpers)."""

from dataclasses import replace
from unittest.mock import MagicMock

from _spell_casting_helpers import _RACIAL_SPEC, _cast, _cast_racial, _spell
from racial_resonance_config_fixture import load_fixture_config


class TestCastSpellResonance:
    async def test_sufficient_focus_deducts(self):
        _packet, _ctx, persistence, _mut, _ev = await _cast(_spell(focus_cost=3), focus=10)
        persistence.update_player_resources.assert_awaited_once()
        _args, kwargs = persistence.update_player_resources.call_args
        assert kwargs["focus"] == 7  # 10 - 3

    async def test_resonance_accrues_and_persists(self):
        packet, ctx, _p, mutations, events = await _cast(_spell(source="arcane", focus_cost=10), start_resonance=0)
        assert packet["resonance_generated"] == 6
        assert ctx.userdata.resonance.current == 6
        assert packet["state"] == "flickering"
        mutations.update_player_resonance.assert_awaited_once()
        args, kwargs = mutations.update_player_resonance.call_args
        assert args[1] == 6 or kwargs.get("current") == 6
        events.publish_resonance_changed.assert_awaited_once_with(
            ctx.userdata, resonance_track=ctx.userdata.resonance, caster_id="player_1"
        )

    async def test_cantrip_accrues_zero_and_scales_damage(self):
        packet, ctx, persistence, mutations, events = await _cast(
            _spell(tier="cantrip", focus_cost=0, resonance=0), focus=10, level=11
        )
        assert packet["resonance_generated"] == 0
        assert ctx.userdata.resonance.current == 0
        assert packet["damage_dice"] == "3d6"
        mutations.update_player_resonance.assert_not_called()
        persistence.update_player_resources.assert_not_called()
        events.publish_resonance_changed.assert_not_called()

    async def test_packet_shape(self):
        packet, _ctx, _p, _m, _ev = await _cast(_spell(), focus=10)
        for key in ("narration_cue", "audio_cue", "effect", "state", "resonance_generated", "resonance_modifiers"):
            assert key in packet, f"packet missing {key}"
        assert packet["narration_cue"] == "A surge of raw power snaps outward."
        assert packet["audio_cue"] == "SFX-001"
        assert packet["effect"] == "Deals force damage to one target."
        assert packet["resonance_modifiers"] == {"damage_dice": 1, "dc": 0}  # flickering (6)

    async def test_non_cantrip_has_no_damage_dice_key(self):
        packet, _ctx, _p, _m, _ev = await _cast(_spell(tier="standard", focus_cost=3), focus=10)
        assert "damage_dice" not in packet

    async def test_cast_uses_catalog_resonance_over_formula(self):
        packet, _ctx, _p, _m, _ev = await _cast(_spell(source="arcane", focus_cost=10, resonance=3), start_resonance=0)
        assert packet["resonance_generated"] == 3

    async def test_cast_falls_back_to_formula_when_source_unmapped(self):
        # When a spell carries no resonance_by_source entry for its source (in-code builds;
        # catalog rows always do), the cast falls back to calculate_resonance_generated.
        spell = replace(_spell(source="arcane", focus_cost=10), resonance_by_source={})
        packet, _ctx, _p, _m, _ev = await _cast(spell, start_resonance=0)
        assert packet["resonance_generated"] == 6  # ceil(10 * 0.6)

    async def test_primal_casts_via_catalog_baseline_resonance(self):
        packet, ctx, _p, mutations, _ev = await _cast(
            _spell(source="primal", tier="standard", focus_cost=3, resonance=2), start_resonance=0
        )
        assert packet["resonance_generated"] == 2
        assert ctx.userdata.resonance.current == 2
        mutations.update_player_resonance.assert_awaited_once()


def test_racial_spec_stub_matches_seeded_content():
    # Bind the cast tests' _RACIAL_SPEC stub to the REAL seeded table
    # (content/racial_resonance_bonuses.json): a seed-value drift breaks these greens here, not
    # only at the story-007 real-PG capstone. Reads the seed directly (no module-global mutation).
    config = load_fixture_config()
    for (race, key), expected in _RACIAL_SPEC.items():
        assert config[race].modifiers[key] == expected, f"{race}.{key} drifted from the seed"


class TestCastSpellRacialResonance:
    async def test_korath_primal_reduces_generation(self):
        packet, ctx, _m, _c, _e = await _cast_racial(_spell(source="primal", focus_cost=3, resonance=3), race="korath")
        assert packet["resonance_generated"] == 2
        assert ctx.userdata.resonance.current == 2
        assert packet["state"] == "stable"

    async def test_korath_primal_floors_at_zero_and_writes_nothing(self):
        packet, ctx, mutations, _c, _e = await _cast_racial(
            _spell(source="primal", focus_cost=3, resonance=1), race="korath"
        )
        assert packet["resonance_generated"] == 0
        assert ctx.userdata.resonance.current == 0
        mutations.update_player_resonance.assert_not_called()

    async def test_korath_arcane_is_not_reduced(self):
        packet, _ctx, _m, _c, _e = await _cast_racial(_spell(source="arcane", focus_cost=3, resonance=3), race="korath")
        assert packet["resonance_generated"] == 3

    async def test_non_korath_primal_is_not_reduced(self):
        packet, _ctx, _m, _c, _e = await _cast_racial(_spell(source="primal", focus_cost=3, resonance=3), race="human")
        assert packet["resonance_generated"] == 3

    async def test_thessyn_cast_honors_hydrated_flickering_bonus(self):
        packet, ctx, _m, _c, echo_events = await _cast_racial(
            _spell(source="arcane", focus_cost=3, resonance=9), race="thessyn", start_flickering_bonus=1
        )
        assert packet["state"] == "flickering"
        assert "hollow_echo" not in packet
        echo_events.publish_hollow_echo.assert_not_awaited()
        assert ctx.userdata.resonance.flickering_bonus == 1  # cast did not touch it

    async def test_thessyn_cast_without_hydrated_bonus_is_overreach(self):
        packet, ctx, _m, _c, _e = await _cast_racial(
            _spell(source="arcane", focus_cost=3, resonance=9), race="thessyn", start_flickering_bonus=0, d20s=(18,)
        )
        assert packet["state"] == "overreach"
        assert ctx.userdata.resonance.flickering_bonus == 0  # no re-grant in the cast path

    async def test_non_thessyn_at_nine_is_overreach(self):
        packet, _ctx, _m, _c, echo_events = await _cast_racial(
            _spell(source="arcane", focus_cost=3, resonance=9), race="human", d20s=(18,)
        )
        assert packet["state"] == "overreach"
        echo_events.publish_hollow_echo.assert_awaited_once()

    async def test_vaelti_resolves_echo_with_advantage(self):
        packet, _ctx, _m, _c, echo_events = await _cast_racial(
            _spell(source="arcane", focus_cost=3, resonance=9), race="vaelti", d20s=(1, 18)
        )
        assert packet["state"] == "overreach"
        assert packet["hollow_echo"]["band"] == "nothing"
        echo_events.publish_hollow_echo.assert_awaited_once()

    async def test_vaelti_overreach_emits_advance_warning(self):
        warn = MagicMock()
        packet, _ctx, _m, _c, _e = await _cast_racial(
            _spell(source="arcane", focus_cost=3, resonance=9), race="vaelti", d20s=(1, 18), vaelti_warning=warn
        )
        assert packet["state"] == "overreach"
        warn.publish_vaelti_echo_warning.assert_called_once()

    async def test_non_vaelti_overreach_emits_no_warning(self):
        warn = MagicMock()
        packet, _ctx, _m, _c, _e = await _cast_racial(
            _spell(source="arcane", focus_cost=3, resonance=9), race="human", d20s=(18,), vaelti_warning=warn
        )
        assert packet["state"] == "overreach"
        warn.publish_vaelti_echo_warning.assert_not_called()
