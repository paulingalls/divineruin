"""Assert disposition delivery at the room and companion speech boundaries."""

import event_types as E
from background_process import BackgroundProcess
from event_bus import EventBus
from session_data import CompanionState, SessionData


def listen(sd: SessionData) -> EventBus:
    sd.companion = CompanionState(id="companion_sable", name="Sable")
    sd.event_bus = EventBus()
    return sd.event_bus


def assert_named_disposition(
    bg: BackgroundProcess,
    bus: EventBus,
    packets: list[dict],
    *,
    npc_id: str,
    npc_name: str,
    previous: str,
    new: str,
    reason: str,
) -> None:
    (packet,) = [event for event in packets if event["type"] == E.DISPOSITION_CHANGED]
    (event,) = [event for event in bus.drain() if event.event_type == E.DISPOSITION_CHANGED]
    bg._handle_events([event])
    (cue,) = bg._speech_queue
    assert f"interaction with {npc_name}." in cue.instructions, cue.instructions
    expected = dict(npc_id=npc_id, npc_name=npc_name, previous=previous, new=new, reason=reason)
    assert event.payload == expected
    assert packet == {"type": E.DISPOSITION_CHANGED, **expected}
