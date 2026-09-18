"""The Focus gate on a cast, plus the two real-catalog end-to-end casts (fixtures: _spell_casting_helpers)."""

from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock

import pytest
from _spell_casting_helpers import _cast, _known, _player, _spell
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_db_mod

from spell_casting import _cast_spell_impl


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
        queries.get_players_for_update = AsyncMock(
            side_effect=lambda ids, *, conn=None: {i: _player(focus=2) for i in ids}
        )
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
                character_spells_mod=_known(spell.id),
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
        queries.get_players_for_update = AsyncMock(return_value={})  # unknown player -> empty batch
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
        # story-008: the OOC caster row now comes from the id-ordered get_players_for_update batch.
        queries.get_players_for_update = AsyncMock(
            side_effect=lambda ids, *, conn=None: {i: _player(focus=10) for i in ids}
        )
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
                character_spells_mod=_known(spell.id),
            )
        # Deducts nothing — the terrain failure precedes the Focus write.
        persistence.update_player_resources.assert_not_called()
        mutations.update_player_resonance.assert_not_called()


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
        events.publish_resonance_changed.assert_awaited_once_with(
            ctx.userdata, resonance_track=ctx.userdata.resonance, caster_id="player_1"
        )

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
