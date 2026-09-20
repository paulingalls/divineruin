"""LiveKit client-participant helpers for acceptance round-trip tests.

Companion to _livekit.py (server lifecycle). This module owns the *client* side:
minting access tokens, connecting `rtc.Room` participants, awaiting peers, and
collecting received data packets. Kept separate so each file owns one concern.

Two-participant round-trip is the only reliable way to verify the data channel
end-to-end — LiveKit does not deliver packets back to the publishing
participant, so a single-room test silently no-ops.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import timedelta

from livekit import api, rtc

# Matches the dev container's defaults (see _livekit.py and conftest.py:92-94).
DEFAULT_TOKEN_TTL_S = 300


def mint_access_token(
    *,
    api_key: str,
    api_secret: str,
    room_name: str,
    identity: str,
    ttl_s: int = DEFAULT_TOKEN_TTL_S,
    participant_kind: api.AccessToken.ParticipantKind = "standard",
) -> str:
    """Mint a LiveKit access token for `identity` to join `room_name`.

    Mirrors the server-side pattern in apps/server/src/livekit.ts:98 but for
    test participants. Grants room-join + publish-data, no track publishing.
    """
    grants = api.VideoGrants(
        room_join=True,
        room=room_name,
        can_publish=True,
        can_publish_data=True,
        can_subscribe=True,
    )
    token = (
        api.AccessToken(api_key, api_secret)
        .with_identity(identity)
        .with_name(identity)
        .with_grants(grants)
        .with_ttl(timedelta(seconds=ttl_s))
    )
    return token.with_kind(participant_kind).to_jwt()


async def connect_room(ws_url: str, token: str) -> rtc.Room:
    """Connect a new Room to `ws_url` with `token`; return the connected Room.

    Raises if the connection doesn't complete within the SDK's default
    connect_timeout (RoomOptions default).
    """
    room = rtc.Room()
    await room.connect(ws_url, token)
    return room


async def wait_for_peer(
    room: rtc.Room,
    *,
    identity: str,
    timeout: float = 5.0,
) -> rtc.RemoteParticipant:
    """Wait until a remote participant with `identity` is visible in `room`.

    Returns immediately if the peer is already in `room.remote_participants`.
    Otherwise registers a `participant_connected` listener and waits until the
    matching identity appears or `timeout` elapses (raises TimeoutError).

    Mirrors the synchronization pattern in game_events._wait_for_connection
    (apps/agent/game_events.py:20-33) and prologue._wait_for_participant
    (apps/agent/prologue.py:26-42), but matches a specific identity — required
    for two-participant tests where any-peer is insufficient.

    Subscribe-then-poll order closes the race where the peer joins between a
    pre-check and listener registration: register the listener first, then
    snapshot remote_participants — any join that fired during registration is
    captured by the listener, anything older shows up in the snapshot.
    """
    seen = asyncio.Event()
    matched: dict[str, rtc.RemoteParticipant] = {}

    def _on_join(participant: rtc.RemoteParticipant) -> None:
        if participant.identity == identity:
            matched["p"] = participant
            seen.set()

    room.on("participant_connected", _on_join)
    try:
        existing = room.remote_participants.get(identity)
        if existing is not None:
            return existing
        try:
            await asyncio.wait_for(seen.wait(), timeout=timeout)
        except TimeoutError as err:
            present = sorted(room.remote_participants.keys())
            raise TimeoutError(
                f"wait_for_peer: identity={identity!r} not seen within {timeout:.1f}s; present={present}"
            ) from err
    finally:
        room.off("participant_connected", _on_join)
    return matched["p"]


def register_data_packet_collector(
    room: rtc.Room,
    *,
    topic: str,
    queue: asyncio.Queue,
) -> Callable[[], None]:
    """Register a `data_received` listener that pushes packets on `topic` to `queue`.

    Each enqueued item is a `(payload_bytes, participant_identity)` tuple.
    Returns an `unregister()` callable so tests/fixtures can detach the listener
    deterministically; teardown via `room.disconnect()` removes it anyway.

    Topic match is strict equality — substring matches would leak future topics
    sharing the same channel into this collector.
    """

    def _on_data(packet: rtc.DataPacket) -> None:
        if packet.topic != topic:
            return
        identity = packet.participant.identity if packet.participant else ""
        queue.put_nowait((packet.data, identity))

    room.on("data_received", _on_data)

    def _unregister() -> None:
        room.off("data_received", _on_data)

    return _unregister


async def aclose_room(room: rtc.Room) -> None:
    """Disconnect `room` if still connected; swallow errors so teardown is idempotent.

    Catches BaseException so asyncio.CancelledError mid-disconnect during pytest
    teardown does not escape — that would skip every subsequent aclose_room call
    in a pair/group, leaking participant slots on the persistent dev container.
    Cancellation is consciously swallowed here: this helper exists solely for
    deterministic teardown, and a leaked WebSocket survives every test run.
    """
    try:
        if room.isconnected():
            await room.disconnect()
    except BaseException:
        # Best-effort teardown — connection may already be gone, or pytest may
        # be cancelling. Either way, swallowing keeps later cleanups running.
        pass


async def publish_audio_frames(
    room: rtc.Room, frames: list[rtc.AudioFrame], *, name: str = "native-transport-tone"
) -> tuple[rtc.AudioSource, rtc.LocalAudioTrack, rtc.LocalTrackPublication]:
    if not frames:
        raise ValueError("audio fixture produced no frames")
    source = rtc.AudioSource(frames[0].sample_rate, frames[0].num_channels)
    track = rtc.LocalAudioTrack.create_audio_track(name, source)
    options = rtc.TrackPublishOptions()
    options.source = rtc.TrackSource.SOURCE_MICROPHONE
    publication = await room.local_participant.publish_track(track, options)
    for frame in frames:
        await source.capture_frame(frame)
    await source.wait_for_playout()
    return source, track, publication


async def wait_for_audio_track_details(
    room: rtc.Room, *, identity: str, timeout: float = 15.0
) -> tuple[rtc.Track, rtc.RemoteTrackPublication, rtc.RemoteParticipant]:
    matched: asyncio.Future[tuple[rtc.Track, rtc.RemoteTrackPublication, rtc.RemoteParticipant]] = (
        asyncio.get_running_loop().create_future()
    )

    def consider(track: rtc.Track, publication: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant) -> None:
        if not matched.done() and participant.identity == identity and publication.kind == rtc.TrackKind.KIND_AUDIO:
            matched.set_result((track, publication, participant))

    room.on("track_subscribed", consider)
    try:
        participant = room.remote_participants.get(identity)
        if participant:
            for publication in participant.track_publications.values():
                if publication.kind == rtc.TrackKind.KIND_AUDIO and publication.track is not None:
                    return publication.track, publication, participant
        try:
            return await asyncio.wait_for(matched, timeout)
        except TimeoutError as exc:
            raise TimeoutError(f"audio track from {identity!r} was not subscribed") from exc
    finally:
        room.off("track_subscribed", consider)


async def wait_for_audio_track(room: rtc.Room, *, identity: str, timeout: float = 15.0) -> rtc.Track:
    track, _, _ = await wait_for_audio_track_details(room, identity=identity, timeout=timeout)
    return track


async def count_audio_frames(track: rtc.Track, *, timeout: float = 10.0) -> int:
    stream = rtc.AudioStream(track)
    count = 0
    try:
        async with asyncio.timeout(timeout):
            async for _event in stream:
                count += 1
                if count >= 3:
                    break
    except TimeoutError as exc:
        if count == 0:
            raise TimeoutError("microphone audio stream produced no frames") from exc
    finally:
        await stream.aclose()
    if count == 0:
        raise ValueError("microphone audio stream produced no frames")
    return count


async def aclose_audio(source: rtc.AudioSource | None) -> None:
    """Drop any queued frames and close `source`, swallowing errors like aclose_room.

    Same tolerance and same reason: a raise here (including a CancelledError mid-close)
    would skip the room teardown that runs alongside it and leak a participant slot.
    """
    if source is None:
        return
    try:
        source.clear_queue()
        await source.aclose()
    except BaseException:
        pass
