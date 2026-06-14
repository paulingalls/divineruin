"""Tests for cast_spell + get_spell_info (spell_casting.py, M3.3 story-004).

Drives the tools' _impl directly with a mock RunContext + injected mock
db/queries/persistence/resonance-mutations mods (the sample_fixtures seam, the
ability_tools precedent). spells/resonance/leveling run REAL — the seed_spells
autouse fixture supplies the live catalog, and resonance + cantrip dice are pure.
Cast tests that need a precise focus_cost/source inject a controlled Spell via a
mock spells_mod so the arithmetic is independent of catalog tuning; the final
two tests exercise the real catalog end-to-end.
"""

import json
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_db_mod

from spell_casting import _cast_spell_impl, _get_spell_info_impl
from spells import Spell, SpellSource, SpellTier


def _player(focus: int = 10, level: int = 5) -> dict:
    return {
        "player_id": "player_1",
        "name": "Lyra",
        "class": "mage",
        "level": level,
        "focus": {"current": focus, "max": 10},
    }


def _spell(
    *,
    spell_id: str = "test_spell",
    source: SpellSource = "arcane",
    tier: SpellTier = "standard",
    focus_cost: int = 10,
    name: str = "Test Spell",
    resonance: int = 6,
    concentration: bool = False,
) -> Spell:
    # resonance_by_source carries the designed per-spell Resonance the cast path reads
    # (decision resonance-by-source-ssot); default 6 keeps the canonical "flickering"
    # fixture. Pass resonance= to control it (0 for cantrips, a formula-deviating value
    # to prove the catalog wins). concentration= flags a concentration spell (story-006).
    return Spell(
        id=spell_id,
        name=name,
        source=source,
        spell_tier=tier,
        focus_cost=focus_cost,
        mechanics="Deals force damage to one target.",
        narration_cue="A surge of raw power snaps outward.",
        audio_cue="SFX-001",
        resonance_by_source={source: resonance},
        terrain_effects={},
        concentration=concentration,
    )


async def _cast(
    spell: Spell,
    *,
    focus: int = 10,
    level: int = 5,
    start_resonance: int = 0,
    player: dict | None = None,
    spells_mod=None,
):
    """Invoke _cast_spell_impl with mock db/queries/persistence/mutations.

    Returns (parsed_packet, ctx, persistence_mock, mutations_mock, events_mock).
    spells_mod defaults to a mock returning `spell`; pass the real module for
    catalog tests.
    """
    ctx = make_context()
    ctx.userdata.resonance.current = start_resonance
    mock_db, _conn = make_db_mod()
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value=player if player is not None else _player(focus, level))
    persistence = MagicMock()
    persistence.update_player_resources = AsyncMock()
    mutations = MagicMock()
    mutations.update_player_resonance = AsyncMock()
    events = MagicMock()
    events.publish_resonance_changed = AsyncMock()
    if spells_mod is None:
        spells_mod = MagicMock()
        spells_mod.get_spell = MagicMock(return_value=spell)
    raw = await _cast_spell_impl(
        ctx,
        spell.id,
        db_mod=mock_db,
        queries_mod=queries,
        persistence_mod=persistence,
        resonance_mutations_mod=mutations,
        resonance_events_mod=events,
        spells_mod=spells_mod,
    )
    return json.loads(raw), ctx, persistence, mutations, events


class TestCastSpellFocusGate:
    async def test_insufficient_focus_raises_and_deducts_nothing(self):
        # AC1: Focus below focus_cost -> ToolError, no Focus write, no resonance write.
        spell = _spell(focus_cost=5)
        with pytest.raises(ToolError):
            await _cast(spell, focus=2)
        # Re-run capturing the mocks to assert nothing was written.
        ctx = make_context()
        mock_db, _conn = make_db_mod()
        queries = MagicMock()
        queries.get_player = AsyncMock(return_value=_player(focus=2))
        persistence = MagicMock()
        persistence.update_player_resources = AsyncMock()
        mutations = MagicMock()
        mutations.update_player_resonance = AsyncMock()
        spells_mod = MagicMock()
        spells_mod.get_spell = MagicMock(return_value=spell)
        with pytest.raises(ToolError):
            await _cast_spell_impl(
                ctx,
                spell.id,
                db_mod=mock_db,
                queries_mod=queries,
                persistence_mod=persistence,
                resonance_mutations_mod=mutations,
                spells_mod=spells_mod,
            )
        persistence.update_player_resources.assert_not_called()
        mutations.update_player_resonance.assert_not_called()

    async def test_unknown_spell_raises_toolerror(self):
        spells_mod = MagicMock()
        spells_mod.get_spell = MagicMock(side_effect=ValueError("Unknown spell: 'nope'"))
        with pytest.raises(ToolError):
            await _cast(_spell(spell_id="nope"), spells_mod=spells_mod)

    async def test_unknown_player_none_raises(self):
        ctx = make_context()
        mock_db, _conn = make_db_mod()
        queries = MagicMock()
        queries.get_player = AsyncMock(return_value=None)
        persistence = MagicMock()
        persistence.update_player_resources = AsyncMock()
        mutations = MagicMock()
        mutations.update_player_resonance = AsyncMock()
        spells_mod = MagicMock()
        spells_mod.get_spell = MagicMock(return_value=_spell())
        with pytest.raises(ToolError):
            await _cast_spell_impl(
                ctx,
                "test_spell",
                db_mod=mock_db,
                queries_mod=queries,
                persistence_mod=persistence,
                resonance_mutations_mod=mutations,
                spells_mod=spells_mod,
            )

    async def test_primal_without_catalog_resonance_falls_back_and_fails_loud(self):
        # The fallback path: a primal spell that carries NO resonance_by_source entry
        # (an in-code build; catalog rows always do) falls back to the source*terrain
        # formula. Terrain defaults to "normal", absent from PRIMAL_TERRAIN_TABLE, so the
        # fallback raises and the cast fails loud (ToolError) BEFORE any Focus deduction.
        # Catalog primal spells DO carry the baseline and cast fine — see the next test.
        spell = replace(_spell(source="primal", tier="standard", focus_cost=3), resonance_by_source={})
        ctx = make_context()
        mock_db, _conn = make_db_mod()
        queries = MagicMock()
        queries.get_player = AsyncMock(return_value=_player(focus=10))
        persistence = MagicMock()
        persistence.update_player_resources = AsyncMock()
        mutations = MagicMock()
        mutations.update_player_resonance = AsyncMock()
        spells_mod = MagicMock()
        spells_mod.get_spell = MagicMock(return_value=spell)
        with pytest.raises(ToolError):
            await _cast_spell_impl(
                ctx,
                spell.id,
                db_mod=mock_db,
                queries_mod=queries,
                persistence_mod=persistence,
                resonance_mutations_mod=mutations,
                spells_mod=spells_mod,
            )
        # Deducts nothing — the terrain failure precedes the Focus write.
        persistence.update_player_resources.assert_not_called()
        mutations.update_player_resonance.assert_not_called()


class TestCastSpellResonance:
    async def test_sufficient_focus_deducts(self):
        # AC2: Focus is deducted by focus_cost.
        _packet, _ctx, persistence, _mut, _ev = await _cast(_spell(focus_cost=3), focus=10)
        persistence.update_player_resources.assert_awaited_once()
        _args, kwargs = persistence.update_player_resources.call_args
        assert kwargs["focus"] == 7  # 10 - 3

    async def test_resonance_accrues_and_persists(self):
        # AC2: the cast reads the catalog's designed resonance_by_source[arcane]=6; 0 -> 6 = flickering.
        packet, ctx, _p, mutations, events = await _cast(_spell(source="arcane", focus_cost=10), start_resonance=0)
        assert packet["resonance_generated"] == 6
        assert ctx.userdata.resonance.current == 6
        assert packet["state"] == "flickering"
        mutations.update_player_resonance.assert_awaited_once()
        args, kwargs = mutations.update_player_resonance.call_args
        # signature: update_player_resonance(player_id, current, *, conn=)
        assert args[1] == 6 or kwargs.get("current") == 6
        # AC6: a resonance-generating cast pushes the new qualitative state to the HUD.
        events.publish_resonance_changed.assert_awaited_once_with(ctx.userdata)

    async def test_cantrip_accrues_zero_and_scales_damage(self):
        # AC3: cantrip (focus_cost 0) -> 0 resonance, no resonance write, damage via
        # cantrip_damage_dice(level). Level 11 -> "3d6".
        packet, ctx, persistence, mutations, events = await _cast(
            _spell(tier="cantrip", focus_cost=0, resonance=0), focus=10, level=11
        )
        assert packet["resonance_generated"] == 0
        assert ctx.userdata.resonance.current == 0
        assert packet["damage_dice"] == "3d6"
        mutations.update_player_resonance.assert_not_called()
        # A free cantrip deducts no Focus.
        persistence.update_player_resources.assert_not_called()
        # AC6: a cantrip leaves the resonance state unchanged, so it pushes no HUD event.
        events.publish_resonance_changed.assert_not_called()

    async def test_packet_shape(self):
        # AC2: packet returns effect, narration_cue, audio_cue (+ state metadata).
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
        # The catalog's designed resonance_by_source is the SSOT, even when it deviates
        # from the source*focus formula (12/58 spells do — decision resonance-by-source-ssot).
        # focus_cost=10 arcane -> formula ceil(10*0.6)=6, but the designed value (3) wins.
        packet, _ctx, _p, _m, _ev = await _cast(_spell(source="arcane", focus_cost=10, resonance=3), start_resonance=0)
        assert packet["resonance_generated"] == 3

    async def test_cast_falls_back_to_formula_when_source_unmapped(self):
        # When a spell carries no resonance_by_source entry for its source (in-code builds;
        # catalog rows always do), the cast falls back to calculate_resonance_generated.
        spell = replace(_spell(source="arcane", focus_cost=10), resonance_by_source={})
        packet, _ctx, _p, _m, _ev = await _cast(spell, start_resonance=0)
        assert packet["resonance_generated"] == 6  # ceil(10 * 0.6)

    async def test_primal_casts_via_catalog_baseline_resonance(self):
        # The fix: a primal spell reads its catalog baseline resonance_by_source[primal]
        # and casts WITHOUT terrain (terrain layering is future). Previously primal
        # non-cantrips raised on the "normal"-terrain formula; now they generate the
        # designed baseline.
        packet, ctx, _p, mutations, _ev = await _cast(
            _spell(source="primal", tier="standard", focus_cost=3, resonance=2), start_resonance=0
        )
        assert packet["resonance_generated"] == 2
        assert ctx.userdata.resonance.current == 2
        mutations.update_player_resonance.assert_awaited_once()


class TestCastSpellRealCatalog:
    async def test_real_arcane_minor_spell_end_to_end(self):
        # E2E (AC6): real catalog spell + real resonance, only db mocked.
        # arcane_shield_spell: focus_cost 1, arcane -> ceil(1*0.6)=1 generated -> stable.
        import spells as spells_mod

        packet, ctx, persistence, mutations, events = await _cast(
            spells_mod.get_spell("arcane_shield_spell"),
            focus=10,
            start_resonance=0,
            spells_mod=spells_mod,
        )
        assert packet["resonance_generated"] == 1
        assert ctx.userdata.resonance.current == 1
        assert packet["state"] == "stable"
        assert packet["narration_cue"]  # catalog cue, non-empty
        persistence.update_player_resources.assert_awaited_once()
        mutations.update_player_resonance.assert_awaited_once()
        events.publish_resonance_changed.assert_awaited_once_with(ctx.userdata)

    async def test_real_arcane_bolt_cantrip(self):
        import spells as spells_mod

        packet, _ctx, _p, mutations, _ev = await _cast(
            spells_mod.get_spell("arcane_bolt"),
            focus=10,
            level=1,
            spells_mod=spells_mod,
        )
        assert packet["resonance_generated"] == 0
        assert packet["damage_dice"] == "1d6"  # level 1
        mutations.update_player_resonance.assert_not_called()


def _dice_mod(total: int):
    """A dice module whose roll('d20') returns a fixed total (deterministic echo tests)."""
    mod = MagicMock()
    mod.roll = MagicMock(return_value=MagicMock(total=total))
    return mod


async def _cast_echo(
    spell: Spell,
    *,
    focus: int = 10,
    start_resonance: int = 0,
    ward_active: bool = False,
    d20: int = 10,
):
    """Invoke _cast_spell_impl with the M3.2 echo/ward mods injected.

    veil_ward + hollow_echo run REAL (pure); dice_mod is fixed for a deterministic roll and
    echo_events is mocked to assert the publish without touching game_events.
    Returns (parsed_packet, ctx, echo_events_mock).
    """
    ctx = make_context()
    ctx.userdata.resonance.current = start_resonance
    ctx.userdata.veil_ward.active = ward_active
    if ward_active:
        ctx.userdata.veil_ward.source = "cleric"
    mock_db, _conn = make_db_mod()
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value=_player(focus))
    persistence = MagicMock()
    persistence.update_player_resources = AsyncMock()
    mutations = MagicMock()
    mutations.update_player_resonance = AsyncMock()
    events = MagicMock()
    events.publish_resonance_changed = AsyncMock()
    echo_events = MagicMock()
    echo_events.publish_hollow_echo = AsyncMock()
    spells_mod = MagicMock()
    spells_mod.get_spell = MagicMock(return_value=spell)
    raw = await _cast_spell_impl(
        ctx,
        spell.id,
        db_mod=mock_db,
        queries_mod=queries,
        persistence_mod=persistence,
        resonance_mutations_mod=mutations,
        resonance_events_mod=events,
        spells_mod=spells_mod,
        dice_mod=_dice_mod(d20),
        echo_events_mod=echo_events,
    )
    return json.loads(raw), ctx, echo_events


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


# --- M3.4 racial Resonance + concentration wiring (story-006) ---

# The seeded spec values (content/racial_resonance_bonuses.json) the cast path reads via
# racial_resonance.get_racial_resonance_modifier. The stub returns these; the real seeded-table
# lookup is proven by the story-007 real-PG capstone.
_RACIAL_SPEC = {
    ("korath", "primal_reduction"): 1,
    ("thessyn", "flickering_threshold_bonus"): 1,
    ("vaelti", "echo_save_advantage"): True,
}


def _racial_mod():
    """Stub racial_resonance returning the seeded spec values; raises (KeyError) on any
    unexpected (race, key), so a test fails loud if the cast looks up the wrong modifier."""
    mod = MagicMock()
    mod.get_racial_resonance_modifier = MagicMock(side_effect=lambda race, key: _RACIAL_SPEC[(race, key)])
    return mod


def _dice_seq(*totals: int):
    """A dice module whose successive roll('d20') calls return totals in order — lets the
    Vaelti advantage test control BOTH the base roll and the advantage roll."""
    mod = MagicMock()
    mod.roll = MagicMock(side_effect=[MagicMock(total=t) for t in totals])
    return mod


async def _cast_racial(
    spell: Spell,
    *,
    race: str | None = None,
    focus: int = 10,
    level: int = 5,
    start_resonance: int = 0,
    start_concentration: str | None = None,
    d20s: tuple[int, ...] = (10,),
):
    """Invoke _cast_spell_impl with the M3.4 racial + concentration mods injected.

    racial_mod is the seeded-spec stub; concentration_mutations_mod is mocked so the persist is
    asserted without touching the DB; dice_mod is a fixed sequence for deterministic echo rolls.
    Returns (parsed_packet, ctx, mutations_mock, concentration_mock, echo_events_mock).
    """
    ctx = make_context()
    ctx.userdata.resonance.current = start_resonance
    ctx.userdata.concentration.spell_id = start_concentration
    mock_db, _conn = make_db_mod()
    player = _player(focus, level)
    if race is not None:
        player["race"] = race
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value=player)
    persistence = MagicMock()
    persistence.update_player_resources = AsyncMock()
    mutations = MagicMock()
    mutations.update_player_resonance = AsyncMock()
    events = MagicMock()
    events.publish_resonance_changed = AsyncMock()
    echo_events = MagicMock()
    echo_events.publish_hollow_echo = AsyncMock()
    concentration = MagicMock()
    concentration.update_player_concentration = AsyncMock()
    spells_mod = MagicMock()
    spells_mod.get_spell = MagicMock(return_value=spell)
    raw = await _cast_spell_impl(
        ctx,
        spell.id,
        db_mod=mock_db,
        queries_mod=queries,
        persistence_mod=persistence,
        resonance_mutations_mod=mutations,
        resonance_events_mod=events,
        spells_mod=spells_mod,
        dice_mod=_dice_seq(*d20s),
        echo_events_mod=echo_events,
        racial_mod=_racial_mod(),
        concentration_mutations_mod=concentration,
    )
    return json.loads(raw), ctx, mutations, concentration, echo_events


class TestCastSpellRacialResonance:
    async def test_korath_primal_reduces_generation(self):
        # AC: Korath Earth-anchored — a primal cast generates -1 (floor 0). 3 -> 2 -> stable.
        packet, ctx, _m, _c, _e = await _cast_racial(_spell(source="primal", focus_cost=3, resonance=3), race="korath")
        assert packet["resonance_generated"] == 2
        assert ctx.userdata.resonance.current == 2
        assert packet["state"] == "stable"

    async def test_korath_primal_floors_at_zero_and_writes_nothing(self):
        # generated 1 primal -> 0 after -1; a floored cast persists no Resonance (the -1 flows
        # through the existing generated>0 write/publish gates) and leaves the track at 0.
        packet, ctx, mutations, _c, _e = await _cast_racial(
            _spell(source="primal", focus_cost=3, resonance=1), race="korath"
        )
        assert packet["resonance_generated"] == 0
        assert ctx.userdata.resonance.current == 0
        mutations.update_player_resonance.assert_not_called()

    async def test_korath_arcane_is_not_reduced(self):
        # The reduction gates on source==primal: a Korath's ARCANE cast keeps its full generation.
        packet, _ctx, _m, _c, _e = await _cast_racial(_spell(source="arcane", focus_cost=3, resonance=3), race="korath")
        assert packet["resonance_generated"] == 3

    async def test_non_korath_primal_is_not_reduced(self):
        # The reduction gates on race==korath: a Human casting the same primal spell is unreduced.
        packet, _ctx, _m, _c, _e = await _cast_racial(_spell(source="primal", focus_cost=3, resonance=3), race="human")
        assert packet["resonance_generated"] == 3

    async def test_thessyn_plus_one_flickering_threshold(self):
        # AC: Thessyn Deep Adaptation shifts the band up by 1 — resonance 9 classifies as
        # flickering (vs overreach for any other race), so no Hollow Echo fires.
        packet, _ctx, _m, _c, echo_events = await _cast_racial(
            _spell(source="arcane", focus_cost=3, resonance=9), race="thessyn"
        )
        assert packet["state"] == "flickering"
        assert "hollow_echo" not in packet
        echo_events.publish_hollow_echo.assert_not_awaited()

    async def test_non_thessyn_at_nine_is_overreach(self):
        # Contrast: the same resonance 9 with no flickering bonus is overreach and rolls an echo.
        packet, _ctx, _m, _c, echo_events = await _cast_racial(
            _spell(source="arcane", focus_cost=3, resonance=9), race="human", d20s=(18,)
        )
        assert packet["state"] == "overreach"
        echo_events.publish_hollow_echo.assert_awaited_once()

    async def test_vaelti_resolves_echo_with_advantage(self):
        # AC: Vaelti Hyper-awareness — the Overreach echo resolves with advantage (best of two
        # d20s). Rolls [1, 18] -> effective 18 -> "nothing" (a non-Vaelti d20=1 -> "breach").
        packet, _ctx, _m, _c, echo_events = await _cast_racial(
            _spell(source="arcane", focus_cost=3, resonance=9), race="vaelti", d20s=(1, 18)
        )
        assert packet["state"] == "overreach"
        assert packet["hollow_echo"]["band"] == "nothing"
        echo_events.publish_hollow_echo.assert_awaited_once()


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


class TestGetSpellInfo:
    async def test_returns_full_catalog_data(self):
        ctx = make_context()
        raw = await _get_spell_info_impl(ctx, "arcane_bolt")
        info = json.loads(raw)
        assert info["id"] == "arcane_bolt"
        assert info["name"]
        assert info["source"] == "arcane"
        assert info["spell_tier"] == "cantrip"
        assert info["focus_cost"] == 0
        # carries the full M3.3 schema
        for key in ("mechanics", "narration_cue", "audio_cue", "resonance_by_source", "concentration"):
            assert key in info

    async def test_unknown_spell_raises_toolerror(self):
        ctx = make_context()
        with pytest.raises(ToolError):
            await _get_spell_info_impl(ctx, "no_such_spell")
