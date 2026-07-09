"""Arrival refreshes the Veil Ward mirror and pushes the HUD only on change (story-004, M24).

Before M24 the ward was a per-player boolean with no location, so walking around could not change
it. Now it is scope-owned: a party that leaves a warded location is no longer warded, and one that
walks into a Sacred site is. Nothing else re-reads the ward between casts, so if arrival did not
refresh, the indicator would keep lying until the next raise or dismiss.

The re-resolve runs INSIDE apply_arrival's transaction, against the DESTINATION — ``conn`` closes
before ``session.location_id`` is updated, so the session still names the old location at that
point. Hence ``resolve_scope_ward_with_scope(..., location_id=destination_id)`` — arrival needs the scope
too, because VEIL_WARD_CHANGED names it (story-008).

VEIL_WARD_CHANGED is appended to pending_events only when the resolved state changed, mirroring the
corruption block's compute-compare-append shape; it publishes post-commit through the existing loop.
"""

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
    """The bug this step exists to prevent: walking out with the indicator still lit."""
    session = _session(location_ward=_WARD)
    pub, _resolver = await _arrive(session, resolved=None)

    assert session.location_ward is None
    payload = next(c.args[2] for c in pub.call_args_list if c.args[1] == E.VEIL_WARD_CHANGED)
    # No scope wards the party any more, so the event names none.
    assert payload == {"active": False, "scope_kind": None, "scope_id": None, "source": None}


async def test_unwarded_to_unwarded_publishes_no_ward_event():
    """Compute, compare, append only on change — the corruption block's shape."""
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
