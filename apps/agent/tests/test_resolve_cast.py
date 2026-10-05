"""``_resolve_cast``, the shared cast core the tool and the combat phase both call (fixtures: _spell_casting_helpers)."""

from unittest.mock import AsyncMock, MagicMock

from _spell_casting_helpers import _known, _player, _spell
from sample_fixtures import make_context, make_db_mod


class TestResolveCast:
    """``_resolve_cast`` is the shared cast core (story-007): transaction-agnostic (takes the
    caller's ``conn``, opens no tx of its own) and in-memory-PURE — it persists Focus/Resonance/
    concentration via the conn but never mutates session.resonance / session.concentration, so a
    rolled-back caller tx leaves the session pristine. The caller syncs those post-commit from the
    returned ``CastResult`` and flushes its deferred ``events``."""

    async def test_returns_castresult_without_mutating_session(self):
        from spell_casting import CastResult, _resolve_cast

        spell = _spell(source="arcane", focus_cost=3, resonance=6)
        ctx = make_context()
        ctx.userdata.resonance.current = 0
        ctx.userdata.concentration.spell_id = None
        _mock_db, conn = make_db_mod()
        queries = MagicMock()
        queries.get_player = AsyncMock(return_value=_player(focus=10))
        queries.get_players_for_update = AsyncMock(
            side_effect=lambda ids, *, conn=None: {i: _player(focus=10) for i in ids}
        )
        persistence = MagicMock()
        persistence.update_player_resources = AsyncMock()
        mutations = MagicMock()
        mutations.update_player_resonance = AsyncMock()
        spells_mod = MagicMock()
        spells_mod.get_spell = MagicMock(return_value=spell)

        result = await _resolve_cast(
            ctx.userdata,
            spell.id,
            conn=conn,
            queries_mod=queries,
            persistence_mod=persistence,
            resonance_mutations_mod=mutations,
            spells_mod=spells_mod,
            character_spells_mod=_known(spell.id),
        )

        assert isinstance(result, CastResult)
        assert result.packet["resonance_generated"] == 6
        assert result.new_resonance == 6
        assert result.generated == 6
        assert ctx.userdata.resonance.current == 0
        assert ctx.userdata.concentration.spell_id is None
        mutations.update_player_resonance.assert_awaited_once()
        persistence.update_player_resources.assert_awaited_once()

    async def test_concentration_spell_id_returned_not_synced(self):
        from spell_casting import _UNCHANGED, _resolve_cast

        spell = _spell(spell_id="hold_flame", concentration=True, focus_cost=3)
        ctx = make_context()
        ctx.userdata.concentration.spell_id = None
        _mock_db, conn = make_db_mod()
        queries = MagicMock()
        queries.get_player = AsyncMock(return_value=_player(focus=10))
        queries.get_players_for_update = AsyncMock(
            side_effect=lambda ids, *, conn=None: {i: _player(focus=10) for i in ids}
        )
        persistence = MagicMock()
        persistence.update_player_resources = AsyncMock()
        mutations = MagicMock()
        mutations.update_player_resonance = AsyncMock()
        concentration = MagicMock()
        concentration.update_player_concentration = AsyncMock()
        spells_mod = MagicMock()
        spells_mod.get_spell = MagicMock(return_value=spell)

        result = await _resolve_cast(
            ctx.userdata,
            spell.id,
            conn=conn,
            queries_mod=queries,
            persistence_mod=persistence,
            resonance_mutations_mod=mutations,
            concentration_mutations_mod=concentration,
            spells_mod=spells_mod,
            character_spells_mod=_known(spell.id),
        )

        assert result.concentration_spell_id == "hold_flame"
        assert result.concentration_spell_id is not _UNCHANGED
        assert ctx.userdata.concentration.spell_id is None
        concentration.update_player_concentration.assert_awaited_once()

    async def test_non_concentration_cast_returns_unchanged_sentinel(self):
        from spell_casting import _UNCHANGED, _resolve_cast

        spell = _spell(spell_id="bolt", concentration=False, focus_cost=3)
        ctx = make_context()
        _mock_db, conn = make_db_mod()
        queries = MagicMock()
        queries.get_player = AsyncMock(return_value=_player(focus=10))
        queries.get_players_for_update = AsyncMock(
            side_effect=lambda ids, *, conn=None: {i: _player(focus=10) for i in ids}
        )
        persistence = MagicMock()
        persistence.update_player_resources = AsyncMock()
        mutations = MagicMock()
        mutations.update_player_resonance = AsyncMock()
        concentration = MagicMock()
        concentration.update_player_concentration = AsyncMock()
        spells_mod = MagicMock()
        spells_mod.get_spell = MagicMock(return_value=spell)

        result = await _resolve_cast(
            ctx.userdata,
            spell.id,
            conn=conn,
            queries_mod=queries,
            persistence_mod=persistence,
            resonance_mutations_mod=mutations,
            concentration_mutations_mod=concentration,
            spells_mod=spells_mod,
            character_spells_mod=_known(spell.id),
        )

        # A non-concentration cast must be distinguishable from "clear concentration" (None).
        assert result.concentration_spell_id is _UNCHANGED
        concentration.update_player_concentration.assert_not_called()

    async def test_non_primary_caster_writes_onto_own_pool_not_primary(self):
        from spell_casting import _resolve_cast

        spell = _spell(source="arcane", focus_cost=3, resonance=6)
        ctx = make_context(party_member_ids=["player_2"])
        ctx.userdata.resonance.current = 0  # the primary (player_1) pool
        caster = ctx.userdata.party.member("player_2")
        assert caster is not None
        caster.resonance.current = 0
        _mock_db, conn = make_db_mod()
        queries = MagicMock()
        _lock_row = {**_player(focus=10), "player_id": "player_2"}
        queries.get_player = AsyncMock(return_value=_lock_row)
        queries.get_players_for_update = AsyncMock(side_effect=lambda ids, *, conn=None: {i: _lock_row for i in ids})
        persistence = MagicMock()
        persistence.update_player_resources = AsyncMock()
        mutations = MagicMock()
        mutations.update_player_resonance = AsyncMock()
        spells_mod = MagicMock()
        spells_mod.get_spell = MagicMock(return_value=spell)

        result = await _resolve_cast(
            ctx.userdata,
            spell.id,
            conn=conn,
            caster=caster,
            queries_mod=queries,
            persistence_mod=persistence,
            resonance_mutations_mod=mutations,
            spells_mod=spells_mod,
            character_spells_mod=_known(spell.id),
        )

        assert list(queries.get_players_for_update.await_args.args[0]) == ["player_2"]
        assert persistence.update_player_resources.await_args.args[0] == "player_2"
        assert mutations.update_player_resonance.await_args.args[0] == "player_2"
        assert result.new_resonance == 6
        assert ctx.userdata.resonance.current == 0
        assert caster.resonance.current == 0  # in-memory PURE — caller syncs post-commit
