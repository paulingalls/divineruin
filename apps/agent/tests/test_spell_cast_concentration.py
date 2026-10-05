from _spell_casting_helpers import _cast, _cast_racial, _spell


class TestCastSpellDecay:
    async def test_human_decays_two_before_generation(self):
        _packet, ctx, _m, _c, _e = await _cast_racial(
            _spell(source="arcane", focus_cost=3, resonance=3), race="human", start_resonance=7
        )
        assert ctx.userdata.resonance.current == 8

    async def test_non_human_decays_one_universal_base(self):
        _packet, ctx, _p, _m, _e = await _cast(_spell(source="arcane", focus_cost=3, resonance=3), start_resonance=7)
        assert ctx.userdata.resonance.current == 9

    async def test_human_decay_floors_at_zero(self):
        _packet, ctx, _m, _c, _e = await _cast_racial(
            _spell(source="arcane", focus_cost=3, resonance=2), race="human", start_resonance=1
        )
        assert ctx.userdata.resonance.current == 2

    async def test_cantrip_skips_decay(self):
        _packet, ctx, _p, _m, _e = await _cast(_spell(tier="cantrip", focus_cost=0, resonance=0), start_resonance=9)
        assert ctx.userdata.resonance.current == 9


class TestCastSpellConcentration:
    async def test_concentration_spell_sets_active(self):
        _packet, ctx, _m, concentration, _e = await _cast_racial(
            _spell(spell_id="hold_flame", concentration=True), focus=10
        )
        assert ctx.userdata.concentration.spell_id == "hold_flame"
        concentration.update_player_concentration.assert_awaited_once()
        args, _kwargs = concentration.update_player_concentration.call_args
        assert args[0] == "player_1"
        assert args[1] == "hold_flame"

    async def test_new_concentration_ends_prior(self):
        _packet, ctx, _m, concentration, _e = await _cast_racial(
            _spell(spell_id="new_spell", concentration=True), start_concentration="old_spell"
        )
        assert ctx.userdata.concentration.spell_id == "new_spell"
        concentration.update_player_concentration.assert_awaited_once()
        _args, _kwargs = concentration.update_player_concentration.call_args
        assert _args[1] == "new_spell"

    async def test_non_concentration_spell_leaves_concentration_untouched(self):
        _packet, ctx, _m, concentration, _e = await _cast_racial(
            _spell(spell_id="bolt", concentration=False), start_concentration="old_spell"
        )
        assert ctx.userdata.concentration.spell_id == "old_spell"
        concentration.update_player_concentration.assert_not_called()

    async def test_non_primary_caster_syncs_onto_own_member_not_primary(self):
        _packet, ctx, _m, concentration, _e = await _cast_racial(
            _spell(spell_id="hold_flame", concentration=True, resonance=6),
            caster_id="player_2",
            party_member_ids=["player_2"],
        )
        caster = ctx.userdata.party.member("player_2")
        assert caster is not None
        assert caster.concentration.spell_id == "hold_flame"
        assert caster.resonance.current == 6
        concentration.update_player_concentration.assert_awaited_once()
        assert concentration.update_player_concentration.await_args.args[0] == "player_2"

        primary = ctx.userdata.party.primary
        assert primary.concentration.spell_id is None
        assert primary.resonance.current == 0
