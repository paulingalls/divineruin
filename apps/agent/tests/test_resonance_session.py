"""Session wiring for the M3.1 Resonance system (story-003).

Resonance becomes live in a session here: SessionData carries a ResonanceTrack
whose stable/flickering/overreach STATE is derived (never stored), a short/long
rest resets it to stable/0 and persists via story-002, and a RESONANCE_CHANGED
event pushes {state, current, max} to the client over the game_events channel.

The rest reset is M3.1's only live resonance mutation (generation-on-cast is M3.3,
which reuses publish_resonance_changed). No live rest @function_tool exists yet, so
these tests drive the building blocks directly and prove them composed end to end —
mirroring the SessionData(room=None) + patched-publish_game_event style of
test_combat_durability.py.

Spec: docs/game_mechanics/game_mechanics_magic.md §Resonance States (100-106),
§Resonance Decay — full reset on rest (130).
"""

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
    # The Thessyn Deep Adaptation bonus (story-006) lives on the track, so EVERY reader of .state
    # (the cast packet, the HUD push) derives the SAME shifted band and cannot diverge. current=9
    # with bonus 1 classifies as flickering, where the default bonus 0 gives overreach.
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


async def test_publish_resonance_changed_emits_state_only():
    session = _session(current=0)

    with patch.object(resonance_events, "publish_game_event", AsyncMock()) as pub:
        await publish_resonance_changed(session)

    pub.assert_awaited_once()
    args, _ = pub.call_args
    room, event_type, payload, event_bus = args
    assert event_type == E.RESONANCE_CHANGED
    # No-number spec (magic.md:98): the wire carries the qualitative state only.
    assert payload == {"state": "stable"}
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
    assert payload == {"state": "stable"}
