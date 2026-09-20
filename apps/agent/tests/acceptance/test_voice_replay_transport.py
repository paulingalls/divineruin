from __future__ import annotations

import asyncio
import hashlib
import json
import wave
from pathlib import Path
from uuid import uuid4

import pytest
from acceptance._livekit_client import aclose_audio, aclose_room, connect_room, mint_access_token
from acceptance.seeds import seed_player
from livekit import rtc

import db
import db_mutations
from voice_replay import append_evidence_row, assert_inventory_result, execute_with_evidence
from voice_replay_audio import (
    capture_received_audio,
    load_checked_clip,
    publish_checked_audio,
    write_wav,
)

_ROOT = Path(__file__).parents[4]
_CLIP = _ROOT / "apps/agent/tests/fixtures/voice_replay/gather_herbs.wav"


async def _rooms(server: dict[str, str], identities: list[str]):
    name = f"voice-replay-{uuid4().hex[:10]}"
    rooms = []
    for identity in identities:
        token = mint_access_token(
            api_key=server["api_key"],
            api_secret=server["api_secret"],
            room_name=name,
            identity=identity,
        )
        rooms.append(await connect_room(server["ws_url"], token))
    return rooms


async def _publish_track(room: rtc.Room, *, name: str, sample_rate: int, channels: int):
    source = rtc.AudioSource(sample_rate, channels, queue_size_ms=100)
    track = rtc.LocalAudioTrack.create_audio_track(name, source)
    options = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    await room.local_participant.publish_track(track, options)
    return source


async def _publish_silence(room: rtc.Room) -> rtc.AudioSource:
    """A decoy audio track carrying only silence. A capture that takes whichever audio track it can
    reach, rather than the named publisher's, comes back with this instead of the replayed speech."""
    source = await _publish_track(room, name="decoy", sample_rate=48_000, channels=1)
    for _ in range(5):
        await source.capture_frame(
            rtc.AudioFrame(data=b"\0" * 9_600, sample_rate=48_000, num_channels=1, samples_per_channel=4_800)
        )
    return source


@pytest.mark.parametrize(("repetition", "already_subscribed"), [(0, False), (1, True)])
async def test_checked_pcm_crosses_real_livekit_from_named_publisher(
    livekit_server: dict[str, str], tmp_path: Path, repetition: int, already_subscribed: bool
):
    """`already_subscribed` picks which selector runs: the decoy reaches the player either before
    the capture starts (the publication lookup) or after it (the subscription handler)."""
    clip = load_checked_clip(_CLIP)
    # the decoy joins first, so a selector that walks participants instead of naming one reaches it first
    decoy, player, agent = await _rooms(livekit_server, ["voice-decoy", "voice-player", "voice-agent"])
    sources: list[rtc.AudioSource] = []
    stop = asyncio.Event()
    capture: asyncio.Task | None = None
    try:
        if already_subscribed:
            sources.append(await _publish_silence(decoy))
            source = await _publish_track(
                agent, name=f"checked-input-{repetition}", sample_rate=clip.sample_rate, channels=clip.channels
            )
            sources.append(source)
            await asyncio.sleep(1.0)

        capture = asyncio.create_task(
            capture_received_audio(player, publisher_identity="voice-agent", stop=stop, timeout=20)
        )
        await asyncio.sleep(0.5)  # let the capture register its subscription handler

        if not already_subscribed:
            sources.append(await _publish_silence(decoy))
            await asyncio.sleep(0.5)
            source = await _publish_track(
                agent, name=f"checked-input-{repetition}", sample_rate=clip.sample_rate, channels=clip.channels
            )
            sources.append(source)

        published = await publish_checked_audio(source, clip, queue_size_ms=100, max_queue_ms=150)
        stop.set()
        received = await capture
        assert published.published_pcm_sha256 == clip.pcm_sha256
        assert published.published_bytes == len(clip.pcm)
        assert received.publisher_identity == "voice-agent"
        samples = memoryview(received.pcm).cast("h")
        # The named publisher's speech measures ~1670 mean amplitude here; the decoy's silence
        # survives the Opus round trip at ~0.02, so this floor separates the two publishers.
        assert sum(abs(sample) for sample in samples) / len(samples) > 100
        output = tmp_path / f"received-{repetition}.wav"
        write_wav(output, received.pcm, sample_rate=received.sample_rate)
        with wave.open(str(output), "rb") as wav:
            assert wav.getnframes() > 0 and wav.getnchannels() == 1
    finally:
        stop.set()
        if capture is not None:
            await asyncio.gather(capture, return_exceptions=True)
        await asyncio.gather(*(aclose_audio(source) for source in sources))
        await asyncio.gather(*(aclose_room(room) for room in (agent, player, decoy)))


def _recording_closer(sink: list[str], name: str):
    async def close() -> None:
        sink.append(name)

    return close


async def test_timeout_and_cancellation_persist_failure_and_close_owned_newest_first(tmp_path: Path):
    for cancellation in (False, True):
        closed: list[str] = []
        path = tmp_path / f"failure-{cancellation}.jsonl"

        async def operation(_row, *, cancel=cancellation):
            if cancel:
                raise asyncio.CancelledError
            raise TimeoutError("no output")

        with pytest.raises((TimeoutError, asyncio.CancelledError)):
            await execute_with_evidence(
                operation,
                [_recording_closer(closed, "room"), _recording_closer(closed, "source")],
                path,
                {"scenario": "affected"},
            )
        row = json.loads(path.read_text().strip())
        assert row["completion"] == "failed"
        assert row["cleanup"] == {"complete": True, "errors": []}
        # newest-first: the source publishing into a room is released before the room itself
        assert closed == ["source", "room"]


async def test_owned_cleanup_failure_reaches_the_row_and_its_validator(tmp_path: Path):
    path = tmp_path / "cleanup.jsonl"
    seen: list[dict] = []

    async def stuck() -> None:
        raise RuntimeError("audio source stuck")

    async def operation(row) -> None:
        row["repetition"] = 0

    def validate(row) -> None:
        seen.append(json.loads(json.dumps(row)))
        raise ValueError("row rejected")

    with pytest.raises(ValueError, match="row rejected"):
        await execute_with_evidence(operation, [stuck], path, {"scenario": "affected"}, validate=validate)

    # the validator judges the measured teardown, not a cleanup field the operation wrote for itself
    assert seen[0]["cleanup"] == {"complete": False, "errors": ["RuntimeError: audio source stuck"]}
    row = json.loads(path.read_text().strip())
    assert row["completion"] == "failed"
    assert row["diagnostic"] == "ValueError: row rejected"


async def test_real_db_inventory_assertion_rejects_missing_and_duplicate_grant(reset_db_pool: str):
    pool = await db.get_pool()
    player_id = f"voice_transport_{uuid4().hex[:8]}"
    await seed_player(pool, player_id=player_id)
    before: dict[str, int] = {}
    output = {"materials": ["quality_wood", "quality_wood"]}
    with pytest.raises(AssertionError, match="inventory delta"):
        await assert_inventory_result(pool, player_id, before, output)

    await db_mutations.add_inventory_item(player_id, "quality_wood", 2, conn=pool)
    delta = await assert_inventory_result(pool, player_id, before, output)
    assert delta == {"quality_wood": 2}

    await db_mutations.add_inventory_item(player_id, "quality_wood", 2, conn=pool)
    with pytest.raises(AssertionError, match="inventory delta"):
        await assert_inventory_result(pool, player_id, before, output)


def test_append_evidence_row_is_durable_jsonl(tmp_path: Path):
    path = tmp_path / "rows.jsonl"
    row = {"completion": "failed", "diagnostic": "fault"}
    append_evidence_row(path, row)
    assert json.loads(path.read_text()) == row
    assert hashlib.sha256(path.read_bytes()).hexdigest()
