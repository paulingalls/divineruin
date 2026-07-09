"""Wire-contract tests for the RESONANCE_CHANGED push (story-004 M4).

The HUD renders only the qualitative Resonance state and MUST NOT show a number
(no-number spec game_mechanics_magic.md:98, concern 05f). So publish_resonance_changed
narrows its payload to {"state", "caster_id"} — the raw `current` value and the display
`max` are dropped from the wire. The number still lives in the DB (persistence) and
in-session (ResonanceTrack.current); it just never crosses to the client. `caster_id`
(M14 story-004) discriminates WHICH party member the state belongs to so a multi-player
client updates only its local player's HUD; it defaults to the session primary.
"""

from unittest.mock import AsyncMock, patch

import event_types as E
import resonance_events
from caster_state import ResonanceTrack
from party_state import PartyMember
from resonance_events import publish_resonance_changed
from session_data import SessionData


def _session(*, current: int = 0) -> SessionData:
    session = SessionData(player_id="p1", location_id="loc1", room=None)
    session.resonance.current = current
    return session


async def _published_payload(session: SessionData) -> dict:
    with patch.object(resonance_events, "publish_game_event", AsyncMock()) as pub:
        await publish_resonance_changed(session)
    pub.assert_awaited_once()
    _room, event_type, payload, _event_bus = pub.call_args.args
    assert event_type == E.RESONANCE_CHANGED
    return payload


async def test_payload_carries_state_and_caster_id():
    payload = await _published_payload(_session(current=0))
    assert payload == {"state": "stable", "caster_id": "p1"}


async def test_payload_omits_the_raw_number():
    # AC4: the wire never carries the resonance number — only the qualitative state.
    payload = await _published_payload(_session(current=7))
    assert payload["state"] == "flickering"
    assert "current" not in payload
    assert "max" not in payload


async def test_payload_state_tracks_every_band():
    for current, expected_state in [
        (0, "stable"),
        (4, "stable"),
        (5, "flickering"),
        (8, "flickering"),
        (9, "overreach"),
    ]:
        payload = await _published_payload(_session(current=current))
        assert payload == {"state": expected_state, "caster_id": "p1"}


async def test_caster_id_defaults_to_session_primary():
    # An explicit caster_id override discriminates a non-primary member; the default is the primary.
    payload = await _published_payload(_session(current=0))
    assert payload["caster_id"] == "p1"


async def test_explicit_track_and_caster_id_push_that_member():
    # M14 story-004: the phase loop pushes each member's OWN track under its OWN caster_id, so the
    # payload's state derives from the passed track (not the session primary's) and carries that id.
    session = _session(current=0)  # primary is "stable" (0)
    member = PartyMember(
        player_id="p2",
        resonance=ResonanceTrack(current=9),  # overreach
        concentration=session.concentration,
    )
    with patch.object(resonance_events, "publish_game_event", AsyncMock()) as pub:
        await publish_resonance_changed(session, resonance_track=member.resonance, caster_id=member.player_id)
    _room, event_type, payload, _event_bus = pub.call_args.args
    assert event_type == E.RESONANCE_CHANGED
    assert payload == {"state": "overreach", "caster_id": "p2"}
