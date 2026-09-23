from __future__ import annotations

from session_data import SessionData


async def promote_after_departure(sd: SessionData, departed_id: str, session: object) -> None:
    successor = sd.handoff_primary(departed_id)
    room_io = getattr(session, "room_io", None)
    if room_io is None:
        raise RuntimeError("A running session has no RoomIO for primary hand-off")
    room_io.set_participant(successor)
    if sd.background is not None:
        await sd.background.primary_changed()
