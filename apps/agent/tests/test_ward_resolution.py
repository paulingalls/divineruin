"""Resolution ORs scopes without stacking effects; check the in-memory encounter first because it is free."""

from unittest.mock import AsyncMock, MagicMock

import pytest

import ward_resolution
from session_data import CombatState, SessionData
from veil_ward import WardScope


@pytest.fixture(autouse=True)
def default_unwarded_scope():
    """Shadow the global autouse stub — this suite tests the resolver itself."""
    yield


_LOCATION_WARD = {"source": "cleric", "expires_at": None, "dismissible": True}
_ENCOUNTER_WARD = {"source": "paladin", "rounds_remaining": 3}


def _session(*, location_id: str = "thornwatch_keep", encounter_ward: dict | None = None) -> SessionData:
    session = SessionData(player_id="p1", location_id=location_id)
    if encounter_ward is not None:
        session.combat_state = CombatState(
            combat_id="c1", participants=[], initiative_order=[], veil_ward=encounter_ward
        )
    return session


def _ward_mod(location_ward: dict | None) -> MagicMock:
    mod = MagicMock()
    mod.read_active_ward = AsyncMock(return_value=location_ward)
    return mod


async def test_unwarded_session_resolves_to_none():
    mod = _ward_mod(None)
    assert await ward_resolution.resolve_scope_ward(_session(), conn=MagicMock(), ward_mutations_mod=mod) is None


async def test_location_ward_covers_the_session():
    mod = _ward_mod(_LOCATION_WARD)
    ward = await ward_resolution.resolve_scope_ward(_session(), conn=MagicMock(), ward_mutations_mod=mod)
    assert ward == _LOCATION_WARD
    mod.read_active_ward.assert_awaited_once()
    scope = mod.read_active_ward.call_args.args[0]
    assert scope == WardScope.location("thornwatch_keep")


async def test_encounter_ward_wins_and_never_hits_the_db():
    mod = _ward_mod(None)
    session = _session(encounter_ward=_ENCOUNTER_WARD)

    ward = await ward_resolution.resolve_scope_ward(session, conn=MagicMock(), ward_mutations_mod=mod)

    assert ward == _ENCOUNTER_WARD
    mod.read_active_ward.assert_not_awaited()


async def test_encounter_ward_short_circuits_even_when_a_location_ward_also_covers():
    """Overlapping ward effects do not stack."""
    mod = _ward_mod(_LOCATION_WARD)
    session = _session(encounter_ward=_ENCOUNTER_WARD)

    assert (
        await ward_resolution.resolve_scope_ward(session, conn=MagicMock(), ward_mutations_mod=mod) == _ENCOUNTER_WARD
    )
    mod.read_active_ward.assert_not_awaited()


async def test_combat_without_a_ward_falls_through_to_the_location():
    mod = _ward_mod(_LOCATION_WARD)
    session = _session(encounter_ward=None)
    session.combat_state = CombatState(combat_id="c1", participants=[], initiative_order=[])

    assert await ward_resolution.resolve_scope_ward(session, conn=MagicMock(), ward_mutations_mod=mod) == _LOCATION_WARD


async def test_location_id_override_resolves_a_different_scope():
    """Arrival resolves its destination before session.location_id changes."""
    mod = _ward_mod(_LOCATION_WARD)

    await ward_resolution.resolve_scope_ward(
        _session(location_id="old_hall"), conn=MagicMock(), location_id="new_hall", ward_mutations_mod=mod
    )

    assert mod.read_active_ward.call_args.args[0] == WardScope.location("new_hall")


async def test_fails_loud_on_an_empty_location():
    """An empty scope id could silently query the wrong rows."""
    mod = _ward_mod(None)
    with pytest.raises(ValueError):
        await ward_resolution.resolve_scope_ward(_session(location_id=""), conn=MagicMock(), ward_mutations_mod=mod)
    mod.read_active_ward.assert_not_awaited()


async def test_passes_the_callers_conn_through():
    mod = _ward_mod(None)
    conn = MagicMock()
    await ward_resolution.resolve_scope_ward(_session(), conn=conn, ward_mutations_mod=mod)
    assert mod.read_active_ward.call_args.kwargs["conn"] is conn


class TestResolveScopeWardWithScope:
    """Return resolved scope identity so publishers do not duplicate resolution."""

    async def test_unwarded_names_no_scope(self):
        ward, scope = await ward_resolution.resolve_scope_ward_with_scope(
            _session(), conn=MagicMock(), ward_mutations_mod=_ward_mod(None)
        )
        assert ward is None
        assert scope is None

    async def test_encounter_ward_names_the_encounter_scope(self):
        ward, scope = await ward_resolution.resolve_scope_ward_with_scope(
            _session(encounter_ward=_ENCOUNTER_WARD), conn=MagicMock(), ward_mutations_mod=_ward_mod(None)
        )
        assert ward == _ENCOUNTER_WARD
        assert scope == WardScope.encounter("c1")

    async def test_location_ward_names_the_location_scope(self):
        ward, scope = await ward_resolution.resolve_scope_ward_with_scope(
            _session(), conn=MagicMock(), ward_mutations_mod=_ward_mod(_LOCATION_WARD)
        )
        assert ward == _LOCATION_WARD
        assert scope == WardScope.location("thornwatch_keep")

    async def test_encounter_scope_wins_over_a_covering_location(self):
        ward, scope = await ward_resolution.resolve_scope_ward_with_scope(
            _session(encounter_ward=_ENCOUNTER_WARD),
            conn=MagicMock(),
            ward_mutations_mod=_ward_mod(_LOCATION_WARD),
        )
        assert ward == _ENCOUNTER_WARD
        assert scope is not None
        assert scope.kind == "encounter"

    async def test_location_id_override_names_the_destination(self):
        _ward, scope = await ward_resolution.resolve_scope_ward_with_scope(
            _session(), conn=MagicMock(), location_id="emberfall", ward_mutations_mod=_ward_mod(_LOCATION_WARD)
        )
        assert scope == WardScope.location("emberfall")

    async def test_resolve_scope_ward_delegates_and_drops_the_scope(self):
        mod = _ward_mod(_LOCATION_WARD)
        assert await ward_resolution.resolve_scope_ward(_session(), conn=MagicMock(), ward_mutations_mod=mod) == (
            _LOCATION_WARD
        )
