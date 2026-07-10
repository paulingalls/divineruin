"""Tests for veil_ward_events.publish_veil_ward_changed (story-004, reshaped in story-008; M24).

The ward's client push lives in its own module, mirroring resonance_events.publish_resonance_changed,
because arrival needs it too: a party that walks out of a warded location must not leave its
indicator lit.

The payload is {active, scope_kind, scope_id, source} — no raiser id (veil_ward_scope_model.md §6).
A ward belongs to a scope, so every in-scope client lights up; there is nothing to filter on.
RESONANCE_CHANGED keeps its caster_id because Resonance is per-caster — the asymmetry is deliberate.

``active`` is the party's RESOLVED warded state, never the toggle of the scope the caller just
mutated (§3): on combat end the encounter ward dies, but if a location ward still covers the party
the event must carry active=True. The emitter enforces that structurally — it takes the ward the
resolver returned, not a bare boolean a caller could compute off the wrong scope.
"""

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
    # There is no scope to name when nothing wards the party; the descriptive keys are null
    # rather than a stale scope the client might latch onto.
    pub = await _publish(_session(), None, None)
    assert pub.call_args.args[2] == {
        "active": False,
        "scope_kind": None,
        "scope_id": None,
        "source": None,
    }


async def test_payload_carries_no_caster_id():
    """§6: no raiser id. A ward is scope-owned, so no client may filter itself out of it."""
    pub = await _publish(_session(), _ENCOUNTER_WARD, WardScope.encounter("combat_42"))
    assert "caster_id" not in pub.call_args.args[2]


async def test_pushes_on_the_sessions_room_and_event_bus():
    session = _session()
    pub = await _publish(session, _LOCATION_WARD, WardScope.location("thornwatch_keep"))
    room, _event_type, _payload, event_bus = pub.call_args.args
    assert room is session.room
    assert event_bus is session.event_bus
