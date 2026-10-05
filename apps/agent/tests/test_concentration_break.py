from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import conditions
from caster_state import ConcentrationState, ResonanceTrack
from concentration_break import break_concentration_on_damage
from party_state import PartyMember
from session_data import SessionData
from tests.combat._helpers import _make_combat_state


def _session(spell_id: str | None) -> SessionData:
    session = SessionData(player_id="player_1", location_id="accord_guild_hall", room=None)
    session.concentration.spell_id = spell_id
    return session


def _two_pc_session(primary_spell_id: str | None, member_spell_id: str | None) -> SessionData:
    """A 2-member party (M18): primary "player_1" concentrating on ``primary_spell_id``, non-primary
    "player_2" concentrating on ``member_spell_id`` — so a test can assert the break resolves against
    the DAMAGED member only, leaving the other's concentration untouched."""
    session = _session(primary_spell_id)
    session.party.members.append(
        PartyMember(
            player_id="player_2",
            resonance=ResonanceTrack(),
            concentration=ConcentrationState(spell_id=member_spell_id),
        )
    )
    return session


def _deps(save_total: int | None = None):
    """Mock the helper's three injected mods. save_total feeds the CON-save roll result."""
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value={"attributes": {"constitution": 14}, "level": 5})
    resolver = MagicMock()
    resolver.resolve_saving_throw = MagicMock(return_value=MagicMock(total=save_total))
    concentration_mutations = MagicMock()
    concentration_mutations.update_player_concentration = AsyncMock()
    return queries, resolver, concentration_mutations


class TestBreakConcentrationOnDamage:
    async def test_failed_save_breaks_and_persists(self):
        session = _session("arcane_fly")
        queries, resolver, cm = _deps(save_total=9)

        broken = await break_concentration_on_damage(
            session,
            10,
            incapacitated=False,
            damaged_player_id="player_1",
            queries=queries,
            resolver=resolver,
            concentration_mutations=cm,
        )

        assert broken == "arcane_fly"  # the broken spell, for DM narration
        assert session.concentration.spell_id is None  # in-memory cleared
        cm.update_player_concentration.assert_awaited_once_with("player_1", None, conn=None)
        _args, _kwargs = resolver.resolve_saving_throw.call_args
        assert _args[1] == "constitution" and _args[2] == 10

    async def test_made_save_keeps_concentration(self):
        session = _session("arcane_fly")
        queries, resolver, cm = _deps(save_total=10)

        broken = await break_concentration_on_damage(
            session,
            10,
            incapacitated=False,
            damaged_player_id="player_1",
            queries=queries,
            resolver=resolver,
            concentration_mutations=cm,
        )

        assert broken is None
        assert session.concentration.spell_id == "arcane_fly"
        cm.update_player_concentration.assert_not_called()

    async def test_incapacitated_auto_breaks_without_rolling(self):
        session = _session("arcane_fly")
        queries, resolver, cm = _deps(save_total=20)

        broken = await break_concentration_on_damage(
            session,
            8,
            incapacitated=True,
            damaged_player_id="player_1",
            queries=queries,
            resolver=resolver,
            concentration_mutations=cm,
        )

        assert broken == "arcane_fly"
        assert session.concentration.spell_id is None
        cm.update_player_concentration.assert_awaited_once_with("player_1", None, conn=None)
        queries.get_player.assert_not_called()
        resolver.resolve_saving_throw.assert_not_called()

    async def test_not_concentrating_is_noop(self):
        session = _session(None)
        queries, resolver, cm = _deps(save_total=1)

        broken = await break_concentration_on_damage(
            session,
            10,
            incapacitated=False,
            damaged_player_id="player_1",
            queries=queries,
            resolver=resolver,
            concentration_mutations=cm,
        )

        assert broken is None
        queries.get_player.assert_not_called()
        resolver.resolve_saving_throw.assert_not_called()
        cm.update_player_concentration.assert_not_called()

    async def test_missing_player_holds_concentration(self):
        session = _session("arcane_fly")
        queries, resolver, cm = _deps(save_total=1)
        queries.get_player = AsyncMock(return_value=None)

        broken = await break_concentration_on_damage(
            session,
            10,
            incapacitated=False,
            damaged_player_id="player_1",
            queries=queries,
            resolver=resolver,
            concentration_mutations=cm,
        )

        assert broken is None
        assert session.concentration.spell_id == "arcane_fly"
        resolver.resolve_saving_throw.assert_not_called()
        cm.update_player_concentration.assert_not_called()

    async def test_zero_damage_is_noop(self):
        session = _session("arcane_fly")
        queries, resolver, cm = _deps(save_total=1)

        broken = await break_concentration_on_damage(
            session,
            0,
            incapacitated=False,
            damaged_player_id="player_1",
            queries=queries,
            resolver=resolver,
            concentration_mutations=cm,
        )

        assert broken is None
        assert session.concentration.spell_id == "arcane_fly"
        resolver.resolve_saving_throw.assert_not_called()
        cm.update_player_concentration.assert_not_called()

    async def test_threads_conn_so_break_joins_caller_tx(self):
        # story-007: in combat the break runs inside the phase transaction, so its DB write must use
        # the phase conn (else a phase rollback leaves the break committed). The player fetch reads
        # the in-tx state on the same conn. Incapacitation auto-fails, so this also covers the no-roll
        # path threading the write conn.
        session = _session("arcane_fly")
        queries, resolver, cm = _deps(save_total=9)
        sentinel_conn = object()

        broken = await break_concentration_on_damage(
            session,
            10,
            incapacitated=False,
            damaged_player_id="player_1",
            queries=queries,
            resolver=resolver,
            concentration_mutations=cm,
            conn=sentinel_conn,
        )

        assert broken == "arcane_fly"
        queries.get_player.assert_awaited_once_with("player_1", conn=sentinel_conn)
        cm.update_player_concentration.assert_awaited_once_with("player_1", None, conn=sentinel_conn)


class TestBreakResolvesAgainstDamagedMember:
    async def test_non_primary_break_leaves_primary_untouched(self):
        session = _two_pc_session(primary_spell_id="divine_bless", member_spell_id="arcane_fly")
        queries, resolver, cm = _deps(save_total=1)  # fails -> breaks

        broken = await break_concentration_on_damage(
            session,
            10,
            incapacitated=False,
            damaged_player_id="player_2",
            queries=queries,
            resolver=resolver,
            concentration_mutations=cm,
        )

        assert broken == "arcane_fly"
        assert session.member_state("player_2").concentration.spell_id is None
        assert session.member_state("player_1").concentration.spell_id == "divine_bless"
        queries.get_player.assert_awaited_once_with("player_2", conn=None)
        cm.update_player_concentration.assert_awaited_once_with("player_2", None, conn=None)

    async def test_primary_break_is_unchanged_by_a_second_member(self):
        session = _two_pc_session(primary_spell_id="divine_bless", member_spell_id="arcane_fly")
        queries, resolver, cm = _deps(save_total=1)  # fails -> breaks

        broken = await break_concentration_on_damage(
            session,
            10,
            incapacitated=False,
            damaged_player_id="player_1",
            queries=queries,
            resolver=resolver,
            concentration_mutations=cm,
        )

        assert broken == "divine_bless"
        assert session.member_state("player_1").concentration.spell_id is None
        assert session.member_state("player_2").concentration.spell_id == "arcane_fly"

    async def test_unknown_damaged_player_id_fails_loud(self):
        session = _two_pc_session(primary_spell_id="divine_bless", member_spell_id="arcane_fly")
        queries, resolver, cm = _deps(save_total=1)

        with pytest.raises(ValueError):
            await break_concentration_on_damage(
                session,
                10,
                incapacitated=False,
                damaged_player_id="not_a_member",
                queries=queries,
                resolver=resolver,
                concentration_mutations=cm,
            )


class TestBreakRemovesLinkedCondition:
    def _bless(self):
        return SimpleNamespace(applies_condition="blessed", concentration=True)

    def _spells_mod(self, spell):
        mod = MagicMock()
        mod.get_spell = MagicMock(return_value=spell)
        return mod

    def _bless_a_player(self, source: str = "bless") -> SessionData:
        session = _session("bless")
        state = _make_combat_state()
        ally = state.get_participant("player_1")
        assert ally is not None
        ally.conditions = conditions.apply_condition(ally.conditions, "blessed", source=source)
        session.combat_state = state
        return session

    @staticmethod
    def _player_blessed(session: SessionData) -> bool:
        assert session.combat_state is not None
        ally = session.combat_state.get_participant("player_1")
        assert ally is not None
        return conditions.has_condition(ally.conditions, "blessed")

    async def test_a_second_caster_still_concentrating_keeps_the_buff_alive(self):
        """Condition source alone does not identify the caster for a multi-target Bless."""
        session = _two_pc_session("bless", "bless")  # both concentrating on Bless
        state = _make_combat_state()
        ally = state.get_participant("player_1")
        assert ally is not None
        ally.conditions = conditions.apply_condition(ally.conditions, "blessed", source="bless")
        session.combat_state = state
        queries, resolver, cm = _deps(save_total=1)  # player_1's save fails -> their spell breaks

        broken = await break_concentration_on_damage(
            session,
            10,
            incapacitated=False,
            damaged_player_id="player_1",
            queries=queries,
            resolver=resolver,
            concentration_mutations=cm,
            spells_mod=self._spells_mod(self._bless()),
        )

        assert broken == "bless"  # the damaged caster's own concentration did end...
        assert session.member_state("player_1").concentration.spell_id is None
        assert session.member_state("player_2").concentration.spell_id == "bless"
        assert self._player_blessed(session)

    async def test_break_drops_the_spells_condition_from_participants(self):
        session = self._bless_a_player()
        queries, resolver, cm = _deps(save_total=1)  # fails -> breaks

        broken = await break_concentration_on_damage(
            session,
            10,
            incapacitated=False,
            damaged_player_id="player_1",
            queries=queries,
            resolver=resolver,
            concentration_mutations=cm,
            spells_mod=self._spells_mod(self._bless()),
        )

        assert broken == "bless"
        assert not self._player_blessed(session)

    async def test_held_concentration_keeps_the_condition(self):
        session = self._bless_a_player()
        queries, resolver, cm = _deps(save_total=99)  # holds -> no break

        broken = await break_concentration_on_damage(
            session,
            10,
            incapacitated=False,
            damaged_player_id="player_1",
            queries=queries,
            resolver=resolver,
            concentration_mutations=cm,
            spells_mod=self._spells_mod(self._bless()),
        )

        assert broken is None
        assert self._player_blessed(session)

    async def test_break_strips_threaded_working_state_not_session(self):
        # Regression (working-state-vs-session): the phase loop resolves against a deep-copied WORKING
        # combat state and only adopts it as session.combat_state AFTER commit, so during resolution
        # session.combat_state is a DIFFERENT, pristine object. The strip must hit the WORKING state
        # the caller threads (combat_state=) — the one that actually gets persisted — NOT the pristine
        # session copy. (The earlier tests masked this by making them the same object.)
        session = self._bless_a_player()  # session.combat_state: player_1 blessed (pristine copy)
        working = _make_combat_state()  # the deep-copied state the phase loop persists
        w_ally = working.get_participant("player_1")
        assert w_ally is not None
        w_ally.conditions = conditions.apply_condition(w_ally.conditions, "blessed", source="bless")
        queries, resolver, cm = _deps(save_total=1)  # fails -> breaks

        broken = await break_concentration_on_damage(
            session,
            10,
            incapacitated=False,
            damaged_player_id="player_1",
            queries=queries,
            resolver=resolver,
            concentration_mutations=cm,
            spells_mod=self._spells_mod(self._bless()),
            combat_state=working,
        )

        assert broken == "bless"
        assert not conditions.has_condition(w_ally.conditions, "blessed")
        assert self._player_blessed(session)

    async def test_non_condition_spell_break_is_harmless(self):
        session = self._bless_a_player(source="other")
        session.concentration.spell_id = "arcane_fly"
        queries, resolver, cm = _deps(save_total=1)
        no_cond = SimpleNamespace(applies_condition=None, concentration=True)

        broken = await break_concentration_on_damage(
            session,
            10,
            incapacitated=False,
            damaged_player_id="player_1",
            queries=queries,
            resolver=resolver,
            concentration_mutations=cm,
            spells_mod=self._spells_mod(no_cond),
        )

        assert broken == "arcane_fly"
        assert self._player_blessed(session)
