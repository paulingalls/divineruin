from __future__ import annotations

import asyncio
import uuid

from acceptance._livekit import ensure_livekit_server
from acceptance._livekit_client import (
    aclose_audio,
    aclose_room,
    connect_room,
    count_audio_frames,
    mint_access_token,
    publish_audio_frames,
    wait_for_audio_track,
    wait_for_peer,
)

from native_transport_probe import build_tone_frames


def test_real_livekit_server_carries_the_deterministic_audio_track() -> None:
    async def exercise() -> None:
        server = ensure_livekit_server(require_docker=True)
        run_id = uuid.uuid4().hex
        room_name = f"native-audio-{run_id}"
        publisher_identity = f"publisher-{run_id}"
        receiver_identity = f"receiver-{run_id}"
        publisher = await connect_room(
            server.ws_url,
            mint_access_token(
                api_key=server.api_key,
                api_secret=server.api_secret,
                room_name=room_name,
                identity=publisher_identity,
            ),
        )
        receiver = None
        source = None
        try:
            receiver = await connect_room(
                server.ws_url,
                mint_access_token(
                    api_key=server.api_key,
                    api_secret=server.api_secret,
                    room_name=room_name,
                    identity=receiver_identity,
                ),
            )
            await asyncio.gather(
                wait_for_peer(publisher, identity=receiver_identity),
                wait_for_peer(receiver, identity=publisher_identity),
            )
            publish_task = asyncio.create_task(publish_audio_frames(publisher, build_tone_frames()))
            track = await wait_for_audio_track(receiver, identity=publisher_identity)
            assert await count_audio_frames(track) > 0
            source, _track, publication = await publish_task
            assert publication.sid
        finally:
            await aclose_audio(source)
            if receiver is not None:
                await aclose_room(receiver)
            await aclose_room(publisher)

    asyncio.run(exercise())
