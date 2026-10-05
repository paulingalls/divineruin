from unittest.mock import AsyncMock, patch

import event_types as E
import resonance_events
from resonance_events import publish_resonance_changed
from rest_mechanics import reset_resonance_on_rest
from session_data import SessionData


def _session(*, current: int | None = None) -> SessionData:
    session = SessionData(player_id="p1", location_id="loc1", room=None)
    if current is not None:
        session.resonance.current = current
    return session


def test_session_default_resonance_is_stable_zero():
    session = SessionData(player_id="p1", location_id="loc1", room=None)
    assert session.resonance.current == 0
    assert session.resonance.state == "stable"


def test_resonance_state_derives_from_current_band():
    session = _session()
    session.resonance.current = 4
    assert session.resonance.state == "stable"
    session.resonance.current = 5
    assert session.resonance.state == "flickering"
    session.resonance.current = 8
    assert session.resonance.state == "flickering"
    session.resonance.current = 9
    assert session.resonance.state == "overreach"


def test_resonance_state_applies_flickering_bonus():
    session = _session()
    session.resonance.current = 9
    assert session.resonance.state == "overreach"  # default bonus 0
    session.resonance.flickering_bonus = 1
    assert session.resonance.state == "flickering"


async def test_rest_reset_zeroes_in_memory_and_persists():
    session = _session(current=7)
    assert session.resonance.state == "flickering"  # precondition: nonzero

    mutations = AsyncMock()
    conn = AsyncMock()  # stands in for a transactional connection; identity-checked below
    await reset_resonance_on_rest(session, conn=conn, resonance_mutations_mod=mutations)

    assert session.resonance.current == 0
    assert session.resonance.state == "stable"
    mutations.reset_player_resonance.assert_awaited_once_with("p1", conn=conn)


async def test_guest_rest_reset_zeroes_and_persists_the_guest_not_the_primary():
    session = _session(current=7)
    guest = SessionData(player_id="p2", location_id="loc1", room=None).party.primary
    guest.resonance.current = 5
    session.party.members.append(guest)
    mutations = AsyncMock()
    with session._bind_authenticated_actor("p2", 1, lambda *_: None):
        await reset_resonance_on_rest(session, resonance_mutations_mod=mutations)
    assert guest.resonance.current == 0
    assert session.party.primary.resonance.current == 7
    mutations.reset_player_resonance.assert_awaited_once_with("p2", conn=None)


async def test_publish_resonance_changed_emits_state_only():
    session = _session(current=0)

    with patch.object(resonance_events, "publish_game_event", AsyncMock()) as pub:
        await publish_resonance_changed(session)

    pub.assert_awaited_once()
    args, _ = pub.call_args
    room, event_type, payload, event_bus = args
    assert event_type == E.RESONANCE_CHANGED
    # No-number spec (magic.md:98): the wire carries the qualitative state + the caster_id
    # discriminator (M14 story-004), never the raw number.
    assert payload == {"state": "stable", "caster_id": "p1"}
    assert room is session.room
    assert event_bus is session.event_bus


async def test_rest_path_persists_reset_and_emits_event_end_to_end():
    session = _session(current=7)
    mutations = AsyncMock()

    with patch.object(resonance_events, "publish_game_event", AsyncMock()) as pub:
        await reset_resonance_on_rest(session, resonance_mutations_mod=mutations)
        await publish_resonance_changed(session)

    mutations.reset_player_resonance.assert_awaited_once_with("p1", conn=None)
    pub.assert_awaited_once()
    _, payload, *_ = pub.call_args.args[1:]
    assert payload == {"state": "stable", "caster_id": "p1"}
