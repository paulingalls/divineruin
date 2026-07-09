"""Tests for ward_resolution.resolve_scope_ward (story-004, M24) — the ONE ward resolver.

veil_ward_scope_model.md §3 is emphatic: "Producers must compute ``active`` from ``is_warded``,
not from the scope they just mutated." A consumer that keys off a single scope turns the ward
light off while the party's casts are still halved. So resolution lives in exactly one function
and every consumer (cast path, tool, movement) calls it.

Resolution is a boolean OR over covering scopes, and the ward's effects do not stack, so the
first covering scope wins. The encounter scope is checked first because it is in-memory and free.

Mock-conn unit tests: the module takes ``conn`` and an injectable ward_mutations_mod, mirroring
the db_mutations_veil_ward seam.
"""

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
    """No ward anywhere. None means absence, never a default-inactive placeholder."""
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
    """The encounter ward lives on CombatState, so resolving it costs no query."""
    mod = _ward_mod(None)
    session = _session(encounter_ward=_ENCOUNTER_WARD)

    ward = await ward_resolution.resolve_scope_ward(session, conn=MagicMock(), ward_mutations_mod=mod)

    assert ward == _ENCOUNTER_WARD
    mod.read_active_ward.assert_not_awaited()


async def test_encounter_ward_short_circuits_even_when_a_location_ward_also_covers():
    """Scopes overlap and ward effects do not stack (§3), so the first covering scope wins."""
    mod = _ward_mod(_LOCATION_WARD)
    session = _session(encounter_ward=_ENCOUNTER_WARD)

    assert (
        await ward_resolution.resolve_scope_ward(session, conn=MagicMock(), ward_mutations_mod=mod) == _ENCOUNTER_WARD
    )
    mod.read_active_ward.assert_not_awaited()


async def test_combat_without_a_ward_falls_through_to_the_location():
    """In an unwarded fight at a warded Sacred site, the party is still warded."""
    mod = _ward_mod(_LOCATION_WARD)
    session = _session(encounter_ward=None)
    session.combat_state = CombatState(combat_id="c1", participants=[], initiative_order=[])

    assert await ward_resolution.resolve_scope_ward(session, conn=MagicMock(), ward_mutations_mod=mod) == _LOCATION_WARD


async def test_location_id_override_resolves_a_different_scope():
    """Arrival resolves the DESTINATION from inside its transaction, before session.location_id moves."""
    mod = _ward_mod(_LOCATION_WARD)

    await ward_resolution.resolve_scope_ward(
        _session(location_id="old_hall"), conn=MagicMock(), location_id="new_hall", ward_mutations_mod=mod
    )

    assert mod.read_active_ward.call_args.args[0] == WardScope.location("new_hall")


async def test_fails_loud_on_an_empty_location():
    """An empty scope id would silently read the wrong rows. WardScope refuses to build one."""
    mod = _ward_mod(None)
    with pytest.raises(ValueError):
        await ward_resolution.resolve_scope_ward(_session(location_id=""), conn=MagicMock(), ward_mutations_mod=mod)
    mod.read_active_ward.assert_not_awaited()


async def test_passes_the_callers_conn_through():
    """It never opens its own connection — it joins the caller's transaction."""
    mod = _ward_mod(None)
    conn = MagicMock()
    await ward_resolution.resolve_scope_ward(_session(), conn=conn, ward_mutations_mod=mod)
    assert mod.read_active_ward.call_args.kwargs["conn"] is conn
