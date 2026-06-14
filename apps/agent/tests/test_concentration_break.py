"""Tests for break_concentration_on_damage (concentration_break.py, story-008, M3.4).

The single production consumer of the concentration engine (concentration.py): when a
concentrating player takes damage it rolls a CON save (DC scales with damage) and ends
concentration on a failed save or incapacitation. Drives the helper directly with mock
queries / save-resolver / concentration-mutations mods, so the save roll and the persist are
deterministic. The pure keep/break decision (concentration_holds) and the DC (check_concentration)
run REAL — they are pure and already covered by test_concentration.py.
"""

from unittest.mock import AsyncMock, MagicMock

from concentration_break import break_concentration_on_damage
from session_data import SessionData


def _session(spell_id: str | None) -> SessionData:
    session = SessionData(player_id="player_1", location_id="accord_guild_hall", room=None)
    session.concentration.spell_id = spell_id
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
        # damage 10 -> DC max(10, 5) = 10; a save total of 9 fails -> concentration ends.
        session = _session("arcane_fly")
        queries, resolver, cm = _deps(save_total=9)

        broken = await break_concentration_on_damage(
            session, 10, incapacitated=False, queries=queries, resolver=resolver, concentration_mutations=cm
        )

        assert broken == "arcane_fly"  # the broken spell, for DM narration
        assert session.concentration.spell_id is None  # in-memory cleared
        cm.update_player_concentration.assert_awaited_once_with("player_1", None)
        # the CON save used the canonical resolver against the damage-scaled DC
        _args, _kwargs = resolver.resolve_saving_throw.call_args
        assert _args[1] == "constitution" and _args[2] == 10

    async def test_made_save_keeps_concentration(self):
        # A save total of 10 meets the DC 10 -> concentration holds; nothing is ended or persisted.
        session = _session("arcane_fly")
        queries, resolver, cm = _deps(save_total=10)

        broken = await break_concentration_on_damage(
            session, 10, incapacitated=False, queries=queries, resolver=resolver, concentration_mutations=cm
        )

        assert broken is None
        assert session.concentration.spell_id == "arcane_fly"
        cm.update_player_concentration.assert_not_called()

    async def test_incapacitated_auto_breaks_without_rolling(self):
        # Dropping incapacitated auto-fails the save (concentration_holds) — no player fetch, no roll.
        session = _session("arcane_fly")
        queries, resolver, cm = _deps(save_total=20)

        broken = await break_concentration_on_damage(
            session, 8, incapacitated=True, queries=queries, resolver=resolver, concentration_mutations=cm
        )

        assert broken == "arcane_fly"
        assert session.concentration.spell_id is None
        cm.update_player_concentration.assert_awaited_once_with("player_1", None)
        queries.get_player.assert_not_called()
        resolver.resolve_saving_throw.assert_not_called()

    async def test_not_concentrating_is_noop(self):
        session = _session(None)
        queries, resolver, cm = _deps(save_total=1)

        broken = await break_concentration_on_damage(
            session, 10, incapacitated=False, queries=queries, resolver=resolver, concentration_mutations=cm
        )

        assert broken is None
        queries.get_player.assert_not_called()
        resolver.resolve_saving_throw.assert_not_called()
        cm.update_player_concentration.assert_not_called()

    async def test_missing_player_holds_concentration(self):
        # A vanished player row (data glitch) fails safe: no save rolled, concentration untouched.
        session = _session("arcane_fly")
        queries, resolver, cm = _deps(save_total=1)
        queries.get_player = AsyncMock(return_value=None)

        broken = await break_concentration_on_damage(
            session, 10, incapacitated=False, queries=queries, resolver=resolver, concentration_mutations=cm
        )

        assert broken is None
        assert session.concentration.spell_id == "arcane_fly"
        resolver.resolve_saving_throw.assert_not_called()
        cm.update_player_concentration.assert_not_called()

    async def test_zero_damage_is_noop(self):
        # A missed attack (0 damage) never threatens concentration — no save rolled.
        session = _session("arcane_fly")
        queries, resolver, cm = _deps(save_total=1)

        broken = await break_concentration_on_damage(
            session, 0, incapacitated=False, queries=queries, resolver=resolver, concentration_mutations=cm
        )

        assert broken is None
        assert session.concentration.spell_id == "arcane_fly"
        resolver.resolve_saving_throw.assert_not_called()
        cm.update_player_concentration.assert_not_called()
