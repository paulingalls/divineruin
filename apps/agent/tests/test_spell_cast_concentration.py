from _spell_casting_helpers import _cast, _cast_racial, _spell


class TestCastSpellDecay:
    """Per-round (cast-paced) Resonance decay (story-010): a real cast sheds one round of
    standing Resonance — base 1/round, +1 for a Human (Adaptive Resonance) -> 2/round —
    before this cast's generation lands. apply_resonance_decay floors at 0."""

    async def test_human_decays_two_before_generation(self):
        # Human start 7 -> decay(7, +1) = 5, + 3 generated = 8 (would be 10 without decay).
        _packet, ctx, _m, _c, _e = await _cast_racial(
            _spell(source="arcane", focus_cost=3, resonance=3), race="human", start_resonance=7
        )
        assert ctx.userdata.resonance.current == 8

    async def test_non_human_decays_one_universal_base(self):
        # A race-less caster decays the universal base 1: start 7 -> 6, + 3 = 9.
        _packet, ctx, _p, _m, _e = await _cast(_spell(source="arcane", focus_cost=3, resonance=3), start_resonance=7)
        assert ctx.userdata.resonance.current == 9

    async def test_human_decay_floors_at_zero(self):
        # Human start 1 -> decay(1, +1) = max(0, 1-2) = 0, + 2 generated = 2.
        _packet, ctx, _m, _c, _e = await _cast_racial(
            _spell(source="arcane", focus_cost=3, resonance=2), race="human", start_resonance=1
        )
        assert ctx.userdata.resonance.current == 2

    async def test_cantrip_skips_decay(self):
        # A cantrip (generated 0) does not shed a round — standing Resonance is untouched (AC6),
        # so the decay gate (generated > 0) never fires.
        _packet, ctx, _p, _m, _e = await _cast(_spell(tier="cantrip", focus_cost=0, resonance=0), start_resonance=9)
        assert ctx.userdata.resonance.current == 9


class TestCastSpellConcentration:
    async def test_concentration_spell_sets_active(self):
        # AC: casting a concentration spell persists it as the active concentration and syncs the
        # in-memory state.
        _packet, ctx, _m, concentration, _e = await _cast_racial(
            _spell(spell_id="hold_flame", concentration=True), focus=10
        )
        assert ctx.userdata.concentration.spell_id == "hold_flame"
        concentration.update_player_concentration.assert_awaited_once()
        args, _kwargs = concentration.update_player_concentration.call_args
        assert args[0] == "player_1"
        assert args[1] == "hold_flame"

    async def test_new_concentration_ends_prior(self):
        # AC: a concentration cast while already concentrating ends the prior — the single-slot
        # overwrite makes the NEW spell the one active concentration.
        _packet, ctx, _m, concentration, _e = await _cast_racial(
            _spell(spell_id="new_spell", concentration=True), start_concentration="old_spell"
        )
        assert ctx.userdata.concentration.spell_id == "new_spell"
        concentration.update_player_concentration.assert_awaited_once()
        _args, _kwargs = concentration.update_player_concentration.call_args
        assert _args[1] == "new_spell"

    async def test_non_concentration_spell_leaves_concentration_untouched(self):
        # A non-concentration cast never breaks an existing concentration (only another
        # concentration spell does).
        _packet, ctx, _m, concentration, _e = await _cast_racial(
            _spell(spell_id="bolt", concentration=False), start_concentration="old_spell"
        )
        assert ctx.userdata.concentration.spell_id == "old_spell"
        concentration.update_player_concentration.assert_not_called()

    async def test_non_primary_caster_syncs_onto_own_member_not_primary(self):
        # story-003 (debt b8169bbe83eb): the OOC post-commit sync must land on the RESOLVED
        # caster's own PartyMember, not the session's primary facade — mirrors combat_ability's
        # caster-resolve-then-sync idiom. player_2 casts a concentration spell that also
        # generates resonance; the primary's pools must stay untouched.
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
