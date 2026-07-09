"""Tests for veil_ward_events.publish_veil_ward_changed (story-004, M24).

The ward's client push moved out of veil_ward_tools into its own module, mirroring
resonance_events.publish_resonance_changed, because arrival now needs it too: a party that walks
out of a warded location must not leave its indicator lit.

The payload stays {active, caster_id} — story-008 rebuilds it as scope-membership. ``active`` is
the party's RESOLVED warded state, never the toggle of the scope the caller just mutated
(veil_ward_scope_model.md §3): on combat end the encounter ward dies, but if a location ward still
covers the party the event must carry active=True.
"""

from unittest.mock import AsyncMock, patch

import event_types as E
import veil_ward_events
from session_data import SessionData


def _session() -> SessionData:
    return SessionData(player_id="p1", location_id="thornwatch_keep")


async def _publish(session, active, caster_id="p1"):
    with patch.object(veil_ward_events, "publish_game_event", AsyncMock()) as pub:
        await veil_ward_events.publish_veil_ward_changed(session, active, caster_id)
    return pub


async def test_publishes_active_ward_with_caster_id():
    pub = await _publish(_session(), True)
    pub.assert_awaited_once()
    _room, event_type, payload, _bus = pub.call_args.args
    assert event_type == E.VEIL_WARD_CHANGED
    assert payload == {"active": True, "caster_id": "p1"}


async def test_publishes_inactive_ward():
    pub = await _publish(_session(), False)
    assert pub.call_args.args[2] == {"active": False, "caster_id": "p1"}


async def test_carries_a_non_primary_caster_id():
    """A non-primary member may raise or dismiss; the push names them, not the primary."""
    pub = await _publish(_session(), True, caster_id="p2")
    assert pub.call_args.args[2]["caster_id"] == "p2"


async def test_pushes_on_the_sessions_room_and_event_bus():
    session = _session()
    pub = await _publish(session, True)
    room, _event_type, _payload, event_bus = pub.call_args.args
    assert room is session.room
    assert event_bus is session.event_bus
