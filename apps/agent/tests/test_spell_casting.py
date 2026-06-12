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
) -> Spell:
    return Spell(
        id=spell_id,
        name=name,
        source=source,
        spell_tier=tier,
        focus_cost=focus_cost,
        mechanics="Deals force damage to one target.",
        narration_cue="A surge of raw power snaps outward.",
        audio_cue="SFX-001",
        resonance_by_source={source: focus_cost},
        terrain_effects={},
        concentration=False,
        level_requirement=1,
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

    async def test_primal_non_cantrip_without_terrain_fails_loud(self):
        # A primal non-cantrip needs a terrain; terrain defaults to "normal", which is
        # NOT in resonance.PRIMAL_TERRAIN_TABLE, so calculate_resonance_generated raises
        # and the cast fails loud (ToolError) until M3.4 terrain wiring lands. The fail
        # happens before any Focus deduction. Cantrips and arcane/divine are unaffected.
        spell = _spell(source="primal", tier="standard", focus_cost=3)
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
        # AC2: arcane multiplier 0.6 -> ceil(10*0.6)=6 generated; 0 -> 6 = flickering.
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
            _spell(tier="cantrip", focus_cost=0), focus=10, level=11
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
        for key in ("mechanics", "narration_cue", "audio_cue", "resonance_by_source", "level_requirement"):
            assert key in info

    async def test_unknown_spell_raises_toolerror(self):
        ctx = make_context()
        with pytest.raises(ToolError):
            await _get_spell_info_impl(ctx, "no_such_spell")
