"""LiveKit room administration for a departing party member."""

import time

from livekit import api


async def remove_player(room_name: str, player_id: str) -> None:
    if not room_name or not player_id:
        raise ValueError("Room name and player identity are required")
    request = api.RoomParticipantIdentity(
        room=room_name,
        identity=player_id,
        revoke_token_ts=int(time.time()) + 1,
    )
    async with api.LiveKitAPI() as client:
        try:
            await client.room.remove_participant(request)
        except api.ServerError as exc:
            # not_found means the participant already left: the mobile client disconnects on
            # its own SESSION_END, which can beat this call. The caller is in the room, so it
            # never means a missing room. Every other code is a real removal failure.
            if exc.code != api.ServerErrorCode.NOT_FOUND:
                raise
