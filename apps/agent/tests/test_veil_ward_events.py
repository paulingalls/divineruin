"""Ward pushes apply to every client in the scope; resonance is per-caster.
Publish resolved party coverage, since ending an encounter ward may leave a location ward active."""

from unittest.mock import AsyncMock, patch

import event_types as E
import veil_ward_events
from session_data import SessionData
from veil_ward import WardScope

_LOCATION_WARD = {"source": "cleric", "expires_at": None, "dismissible": True}
_ENCOUNTER_WARD = {"source": "paladin", "rounds_remaining": 3}


def _session() -> SessionData:
    return SessionData(player_id="p1", location_id="thornwatch_keep")


async def _publish(session, ward, scope):
    with patch.object(veil_ward_events, "publish_game_event", AsyncMock()) as pub:
        await veil_ward_events.publish_veil_ward_changed(session, ward, scope)
    return pub


async def test_publishes_an_active_location_ward_with_its_scope():
    pub = await _publish(_session(), _LOCATION_WARD, WardScope.location("thornwatch_keep"))
    pub.assert_awaited_once()
    _room, event_type, payload, _bus = pub.call_args.args
    assert event_type == E.VEIL_WARD_CHANGED
    assert payload == {
        "active": True,
        "scope_kind": "location",
        "scope_id": "thornwatch_keep",
        "source": "cleric",
    }


async def test_publishes_an_active_encounter_ward_with_its_scope():
    pub = await _publish(_session(), _ENCOUNTER_WARD, WardScope.encounter("combat_42"))
    assert pub.call_args.args[2] == {
        "active": True,
        "scope_kind": "encounter",
        "scope_id": "combat_42",
        "source": "paladin",
    }


async def test_unwarded_publishes_active_false_and_names_no_scope():
    pub = await _publish(_session(), None, None)
    assert pub.call_args.args[2] == {
        "active": False,
        "scope_kind": None,
        "scope_id": None,
        "source": None,
    }


async def test_payload_carries_no_caster_id():
    """A scope-owned ward must not filter out clients by caster id."""
    pub = await _publish(_session(), _ENCOUNTER_WARD, WardScope.encounter("combat_42"))
    assert "caster_id" not in pub.call_args.args[2]


async def test_pushes_on_the_sessions_room_and_event_bus():
    session = _session()
    pub = await _publish(session, _LOCATION_WARD, WardScope.location("thornwatch_keep"))
    room, _event_type, _payload, event_bus = pub.call_args.args
    assert room is session.room
    assert event_bus is session.event_bus
