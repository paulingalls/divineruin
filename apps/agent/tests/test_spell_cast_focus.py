from unittest.mock import AsyncMock, MagicMock

import pytest
from _spell_casting_helpers import _cast, _known, _player, _spell
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_db_mod

from spell_casting import _cast_spell_impl


class TestCastSpellFocusGate:
    async def test_insufficient_focus_raises_and_deducts_nothing(self):
        spell = _spell(focus_cost=5)
        with pytest.raises(ToolError):
            await _cast(spell, focus=2)
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


class TestCastSpellRealCatalog:
    async def test_real_arcane_minor_spell_end_to_end(self):
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
