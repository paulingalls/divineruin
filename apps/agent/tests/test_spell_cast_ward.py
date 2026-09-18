"""The Hollow Echo a cast provokes and the Resonance wards that soften it (fixtures: _spell_casting_helpers)."""

import json
from unittest.mock import AsyncMock, MagicMock

from _spell_casting_helpers import _cast, _cast_echo, _known, _player, _spell
from sample_fixtures import make_context, make_db_mod

from combat_phase import PhaseBeat, advance_combat_phase
from session_data import CombatState
from spell_casting import _cast_spell_impl
from spells import Spell


class TestCastSpellHollowEcho:
    async def test_overreach_cast_rolls_and_returns_band(self):
        # A cast that lands the caster at Overreach (9+) auto-rolls the Hollow Echo.
        # resonance=9 -> new 9 -> overreach; d20=18 -> effective 18 -> "nothing".
        packet, _ctx, echo_events = await _cast_echo(_spell(resonance=9), d20=18)
        assert packet["state"] == "overreach"
        assert packet["hollow_echo"]["band"] == "nothing"
        assert packet["hollow_echo"]["name"] and packet["hollow_echo"]["effect"]
        echo_events.publish_hollow_echo.assert_awaited_once()

    async def test_below_overreach_does_not_roll(self):
        # A cast that stays below Overreach rolls no echo and carries no band.
        packet, _ctx, echo_events = await _cast_echo(_spell(resonance=6))
        assert packet["state"] == "flickering"
        assert "hollow_echo" not in packet
        echo_events.publish_hollow_echo.assert_not_awaited()

    async def test_breach_on_low_roll(self):
        # E2E: injected d20=1 on a ward-less Overreach cast -> "breach" band + published.
        packet, _ctx, echo_events = await _cast_echo(_spell(resonance=9), d20=1)
        assert packet["hollow_echo"]["band"] == "breach"
        echo_events.publish_hollow_echo.assert_awaited_once()

    async def test_cantrip_at_standing_overreach_still_rolls(self):
        # Decision: the echo fires for ANY cast that ENDS at Overreach (9+), including a
        # free cantrip cast while resonance already stands at Overreach. The cantrip adds
        # 0 (no resonance write, no RESONANCE_CHANGED push), but the state is still
        # overreach so the Veil still exacts a Hollow Echo.
        packet, _ctx, echo_events = await _cast_echo(
            _spell(tier="cantrip", focus_cost=0, resonance=0), start_resonance=9, d20=18
        )
        assert packet["resonance_generated"] == 0
        assert packet["state"] == "overreach"
        assert packet["hollow_echo"]["band"] == "nothing"
        echo_events.publish_hollow_echo.assert_awaited_once()


class TestCastSpellWardThroughRealResolver:
    """Non-vacuity proof: the ward gate fires on the PRODUCTION default path.

    The sibling TestCastSpellWard suite injects its own ``ward_resolution_mod``, so it
    never exercises the resolver the cast path actually reaches for. These tests inject
    nothing: the real ``ward_resolution.resolve_scope_ward`` runs, reading the encounter
    ward from memory and, for a location scope, the one stubbed I/O leaf
    (``db_mutations_veil_ward.read_active_ward``).

    Against the previous fixture — which stubbed ``resolve_scope_ward`` itself to return
    None — every assertion here fails: the gate is answered "unwarded" no matter what
    ``combat_state`` holds. That silent answer is concern ec9d730b899d; these tests are
    what make it impossible to reintroduce.
    """

    _WARD = {"source": "cleric", "rounds_remaining": None}

    def _warded_combat(self) -> CombatState:
        return CombatState(
            combat_id="c_nonvacuous",
            participants=[],
            initiative_order=[],
            location_id="accord_guild_hall",
            veil_ward=self._WARD,
        )

    async def test_encounter_ward_halves_generation_via_real_resolver(self):
        # resonance=6 halved to 3 by a ward this cast never injected a resolver to see.
        packet, ctx, _p, _m, _e = await _cast(_spell(resonance=6), combat_state=self._warded_combat())
        assert packet["ward_active"] is True
        assert packet["resonance_generated"] == 3
        assert ctx.userdata.resonance.current == 3

    async def test_unwarded_combat_generates_unhalved_via_real_resolver(self):
        # Same real resolver, no ward on the scope: the stubbed leaf answers "no row".
        combat = self._warded_combat()
        combat.veil_ward = None
        packet, _ctx, _p, _m, _e = await _cast(_spell(resonance=6), combat_state=combat)
        assert packet["ward_active"] is False
        assert packet["resonance_generated"] == 6

    async def test_ward_raised_by_another_member_halves_this_casters_generation(self):
        # AC1: the ward is scope-owned. A Paladin raised it; the caster here is a mage
        # (_player class="mage") and is halved anyway. Nothing keys off who raised it.
        combat = self._warded_combat()
        combat.veil_ward = {"source": "paladin", "rounds_remaining": 3}
        packet, _ctx, _p, _m, _e = await _cast(_spell(resonance=6), combat_state=combat)
        assert packet["ward_active"] is True
        assert packet["resonance_generated"] == 3

    async def test_ward_raised_by_another_member_applies_die_and_dc_penalty(self):
        # AC1: -1 damage die and -1 DC likewise apply per-caster-in-scope, not to the raiser.
        combat = self._warded_combat()
        combat.veil_ward = {"source": "paladin", "rounds_remaining": 3}
        packet, _ctx, _p, _m, _e = await _cast(_spell(resonance=6), combat_state=combat)
        assert packet["resonance_modifiers"] == {"damage_dice": -1, "dc": -1}

    async def test_overreach_echo_takes_ward_bonus_regardless_of_raiser(self):
        # AC3: resonance=18 halved to 9 -> still Overreach. The Paladin's ward lends this mage
        # the +4: d20=12 -> 16 -> "whisper". Without the bonus 12 alone would band "veil_scar".
        combat = self._warded_combat()
        combat.veil_ward = {"source": "paladin", "rounds_remaining": 3}
        packet, _ctx, echo_events = await _cast_echo(_spell(resonance=18), d20=12, combat_state=combat)
        assert packet["state"] == "overreach"
        assert packet["hollow_echo"]["band"] == "whisper"
        echo_events.publish_hollow_echo.assert_awaited_once()

    async def test_overreach_echo_without_ward_bands_harsher(self):
        # Isolates the +4. Both casts resolve their echo against effective_resonance 9 (warded:
        # 18 halved; unwarded: 9 outright), so the high-Resonance modifier is 0 on both sides and
        # the die is 12 on both sides. Only the ward bonus differs: 16 -> whisper vs 12 -> veil_scar.
        combat = self._warded_combat()
        combat.veil_ward = None
        packet, _ctx, _echo = await _cast_echo(_spell(resonance=9), d20=12, combat_state=combat)
        assert packet["state"] == "overreach"
        assert packet["hollow_echo"]["band"] == "veil_scar"


class TestCastUnderADeployedVeilAnchor:
    """AC4 (story-012): a caster standing in a deployed anchor's scope is halved exactly as under a
    Cleric ward. The anchor writes an ordinary location ward, so nothing in the cast path knows or
    cares that an item put it there — which is the property worth pinning.

    Only the DB leaf is stubbed; the real ward_resolution.resolve_scope_ward runs and finds the row.
    """

    _ANCHOR_WARD = {"source": "artificer", "expires_at": None, "dismissible": False}
    _CLERIC_WARD = {"source": "cleric", "expires_at": None, "dismissible": True}

    async def _generated_under(self, monkeypatch, ward) -> int:
        import db_mutations_veil_ward

        monkeypatch.setattr(db_mutations_veil_ward, "read_active_ward", AsyncMock(return_value=ward))
        packet, _ctx, _p, _m, _e = await _cast(_spell(resonance=6))
        return packet["resonance_generated"]

    async def test_a_deployed_anchor_halves_generation(self, monkeypatch):
        assert await self._generated_under(monkeypatch, self._ANCHOR_WARD) == 3

    async def test_it_halves_exactly_as_a_cleric_ward_does(self, monkeypatch):
        # The ward is scope-owned; its source is narration, never mechanics.
        anchor = await self._generated_under(monkeypatch, self._ANCHOR_WARD)
        cleric = await self._generated_under(monkeypatch, self._CLERIC_WARD)
        assert anchor == cleric == 3

    async def test_no_anchor_no_halving(self, monkeypatch):
        assert await self._generated_under(monkeypatch, None) == 6


class TestPartyWideWardedEncounter:
    """AC5 capstone: a two-member party in a warded encounter, ward expiring mid-combat.

    Wires the two halves of story-006 together against real code: the WRAP beat's round clock
    (combat_phase._wrap) and the cast path's ward read (the real ward_resolution.resolve_scope_ward,
    no resolver injected). Both members are halved while the Paladin's 3-round ward stands, and
    neither is halved on the round after it expires.

    The ward is ONE object on the encounter scope; Resonance stays per-caster, each member
    accruing into their own ResonanceTrack. That asymmetry is the milestone's whole rule.
    """

    _MEMBERS = ("player_1", "player_2")

    def _ctx_with_warded_combat(self, rounds_remaining: int):
        ctx = make_context(party_member_ids=["player_2"])
        ctx.userdata.combat_state = CombatState(
            combat_id="c_party",
            participants=[],
            initiative_order=[],
            location_id="accord_guild_hall",
            veil_ward={"source": "paladin", "rounds_remaining": rounds_remaining},
            beat=PhaseBeat.WRAP,
        )
        return ctx

    async def _cast_as(self, ctx, member_id: str, spell: Spell) -> dict:
        mock_db, _conn = make_db_mod()
        queries = MagicMock()
        row = _player()
        queries.get_player = AsyncMock(return_value=row)
        queries.get_players_for_update = AsyncMock(side_effect=lambda ids, *, conn=None: {i: row for i in ids})
        persistence = MagicMock()
        persistence.update_player_resources = AsyncMock()
        mutations = MagicMock()
        mutations.update_player_resonance = AsyncMock()
        events = MagicMock()
        events.publish_resonance_changed = AsyncMock()
        spells_mod = MagicMock()
        spells_mod.get_spell = MagicMock(return_value=spell)
        raw = await _cast_spell_impl(
            ctx,
            spell.id,
            caster_id=member_id,
            db_mod=mock_db,
            queries_mod=queries,
            persistence_mod=persistence,
            resonance_mutations_mod=mutations,
            resonance_events_mod=events,
            spells_mod=spells_mod,
            character_spells_mod=_known(spell.id),
        )
        return json.loads(raw)

    def _tick_wraps(self, ctx, count: int) -> None:
        for _ in range(count):
            ctx.userdata.combat_state.beat = PhaseBeat.WRAP
            next_state, _ = advance_combat_phase(ctx.userdata.combat_state, None)
            ctx.userdata.combat_state = next_state

    async def test_both_members_halved_before_expiry_and_neither_after(self):
        ctx = self._ctx_with_warded_combat(rounds_remaining=3)

        # Round 1, ward standing: every caster in the scope is halved, not just the Paladin.
        for member_id in self._MEMBERS:
            packet = await self._cast_as(ctx, member_id, _spell(resonance=6))
            assert packet["ward_active"] is True, member_id
            assert packet["resonance_generated"] == 3, member_id

        # Three wrap beats elapse; the 3-round ward dies at the third.
        self._tick_wraps(ctx, 3)
        assert ctx.userdata.combat_state.veil_ward is None

        # Round 4, unwarded: neither caster is halved. Nothing lingers.
        for member_id in self._MEMBERS:
            packet = await self._cast_as(ctx, member_id, _spell(resonance=6))
            assert packet["ward_active"] is False, member_id
            assert packet["resonance_generated"] == 6, member_id

    async def test_ward_still_halves_on_the_round_it_expires(self):
        # Two wraps leave rounds_remaining=1: the ward is still up for that round's casts.
        ctx = self._ctx_with_warded_combat(rounds_remaining=3)
        self._tick_wraps(ctx, 2)
        assert ctx.userdata.combat_state.veil_ward["rounds_remaining"] == 1
        packet = await self._cast_as(ctx, "player_2", _spell(resonance=6))
        assert packet["ward_active"] is True
        assert packet["resonance_generated"] == 3

    async def test_resonance_stays_per_caster_under_one_shared_ward(self):
        # One ward, two independent Resonance pools. In combat the cast-paced shed is suppressed,
        # so each member's track carries exactly their own halved generation.
        ctx = self._ctx_with_warded_combat(rounds_remaining=3)
        await self._cast_as(ctx, "player_1", _spell(resonance=6))
        assert ctx.userdata.member_state("player_1").resonance.current == 3
        assert ctx.userdata.member_state("player_2").resonance.current == 0

        await self._cast_as(ctx, "player_2", _spell(resonance=6))
        assert ctx.userdata.member_state("player_1").resonance.current == 3
        assert ctx.userdata.member_state("player_2").resonance.current == 3


class TestCastSpellWard:
    async def test_active_ward_halves_generation(self):
        # resonance=6 halved to 3 -> stable; the packet's resonance_generated reflects the halving.
        packet, ctx, _echo = await _cast_echo(_spell(resonance=6), ward_active=True)
        assert packet["resonance_generated"] == 3
        assert ctx.userdata.resonance.current == 3
        assert packet["state"] == "stable"
        assert packet["ward_active"] is True

    async def test_active_ward_applies_die_and_dc_penalty(self):
        # Ward folds -1 damage die / -1 DC into the net resonance_modifiers (stable {0,0} -> {-1,-1}).
        packet, _ctx, _echo = await _cast_echo(_spell(resonance=6), ward_active=True)
        assert packet["resonance_modifiers"] == {"damage_dice": -1, "dc": -1}

    async def test_ward_softens_the_echo(self):
        # resonance=18 halved to 9 -> still Overreach, but the +4 ward bonus softens the roll:
        # d20=12 -> effective 12+4 = 16 -> "whisper" (vs "veil_scar" without the ward).
        packet, _ctx, echo_events = await _cast_echo(_spell(resonance=18), ward_active=True, d20=12)
        assert packet["state"] == "overreach"
        assert packet["hollow_echo"]["band"] == "whisper"
        echo_events.publish_hollow_echo.assert_awaited_once()
