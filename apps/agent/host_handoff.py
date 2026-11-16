from __future__ import annotations

from session_data import SessionData
from session_room_ownership import transfer_room


async def promote_after_departure(sd: SessionData, departed_id: str, session: object) -> None:
    room_io = getattr(session, "room_io", None)
    if room_io is None:
        raise RuntimeError("A running session has no RoomIO for primary hand-off")
    if sd.primary_player_id != departed_id or len(sd.party.members) < 2 or sd.room is None:
        raise RuntimeError("Primary handoff requires a room and a remaining member")
    await transfer_room(sd.room.name, departed_id, sd.party.members[1].player_id)
    successor = sd.handoff_primary(departed_id)
    room_io.set_participant(successor)
    if sd.background is not None:
        await sd.background.primary_changed()
