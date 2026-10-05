"""Resolve against the destination inside the transaction: session.location_id still names the old location.
Publish only after commit so rolled-back arrival cannot change the HUD."""

from unittest.mock import AsyncMock, MagicMock, patch

import event_types as E
import movement_tools
from session_data import SessionData
from veil_ward import WardScope

_WARD = {"source": "sacred_site", "expires_at": None, "dismissible": False}


def _db_mod():
    mod = MagicMock()
    conn = AsyncMock()
    mod.transaction.return_value.__aenter__ = AsyncMock(return_value=conn)
    mod.transaction.return_value.__aexit__ = AsyncMock(return_value=False)
    mod.extract_exit_connections = MagicMock(return_value={})
    return mod


async def _arrive(session, *, resolved):
    """Drive apply_arrival with the ward resolver stubbed to `resolved` for the destination.

    The resolver returns (ward, scope); an unwarded destination names no scope.
    """
    scope = WardScope.location("greyvale_ruins") if resolved is not None else None
    resolver = AsyncMock(return_value=(resolved, scope))
    with (
        patch.object(movement_tools, "publish_game_event", AsyncMock()) as pub,
        patch.object(movement_tools.ward_resolution, "resolve_scope_ward_with_scope", resolver),
    ):
        await movement_tools.apply_arrival(
            session, "greyvale_ruins", {"name": "Greyvale Ruins"}, db_mod=_db_mod(), mutations=AsyncMock()
        )
    return pub, resolver


def _ward_events(pub):
    return [c.args[1] for c in pub.call_args_list if c.args[1] == E.VEIL_WARD_CHANGED]


def _session(*, location_ward=None) -> SessionData:
    session = SessionData(player_id="p1", location_id="accord_market_square")
    session.location_ward = location_ward
    return session


async def test_arriving_at_a_warded_location_refreshes_the_mirror_and_lights_the_hud():
    session = _session(location_ward=None)
    pub, _resolver = await _arrive(session, resolved=_WARD)

    assert session.location_ward == _WARD
    assert _ward_events(pub) == [E.VEIL_WARD_CHANGED]
    payload = next(c.args[2] for c in pub.call_args_list if c.args[1] == E.VEIL_WARD_CHANGED)
    assert payload == {
        "active": True,
        "scope_kind": "location",
        "scope_id": "greyvale_ruins",
        "source": _WARD["source"],
    }


async def test_leaving_a_warded_location_clears_the_mirror_and_darkens_the_hud():
    session = _session(location_ward=_WARD)
    pub, _resolver = await _arrive(session, resolved=None)

    assert session.location_ward is None
    payload = next(c.args[2] for c in pub.call_args_list if c.args[1] == E.VEIL_WARD_CHANGED)
    assert payload == {"active": False, "scope_kind": None, "scope_id": None, "source": None}


async def test_unwarded_to_unwarded_publishes_no_ward_event():
    session = _session(location_ward=None)
    pub, _resolver = await _arrive(session, resolved=None)

    assert session.location_ward is None
    assert _ward_events(pub) == []


async def test_warded_to_warded_publishes_no_ward_event():
    session = _session(location_ward=_WARD)
    pub, _resolver = await _arrive(session, resolved=_WARD)

    assert _ward_events(pub) == []


async def test_resolves_the_destination_not_the_stale_session_location():
    """conn closes before session.location_id moves, so the destination must be passed explicitly."""
    session = _session()
    _pub, resolver = await _arrive(session, resolved=None)

    assert resolver.await_args is not None
    assert resolver.await_args.kwargs["location_id"] == "greyvale_ruins"
    assert session.location_id == "greyvale_ruins"  # updated only after commit
