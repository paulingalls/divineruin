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


async def _publish(room: rtc.Room, clip, *, name: str):
    source = rtc.AudioSource(clip.sample_rate, clip.channels, queue_size_ms=100)
    track = rtc.LocalAudioTrack.create_audio_track(name, source)
    options = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    publication = await room.local_participant.publish_track(track, options)
    result = await publish_checked_audio(source, clip, queue_size_ms=100, max_queue_ms=150)
    return source, publication, result


@pytest.mark.parametrize("repetition", [0, 1])
async def test_checked_pcm_crosses_real_livekit_from_named_publisher(
    livekit_server: dict[str, str], tmp_path: Path, repetition: int
):
    clip = load_checked_clip(_CLIP)
    agent, player, decoy = await _rooms(livekit_server, ["voice-agent", "voice-player", "voice-decoy"])
    sources: list[rtc.AudioSource] = []
    try:
        decoy_frame = rtc.AudioFrame(
            data=b"\x40\0" * 4_800,
            sample_rate=48_000,
            num_channels=1,
            samples_per_channel=4_800,
        )
        decoy_source = rtc.AudioSource(48_000, 1)
        sources.append(decoy_source)
        decoy_track = rtc.LocalAudioTrack.create_audio_track("decoy", decoy_source)
        await decoy.local_participant.publish_track(decoy_track, rtc.TrackPublishOptions())
        await decoy_source.capture_frame(decoy_frame)

        stop = asyncio.Event()
        capture = asyncio.create_task(
            capture_received_audio(player, publisher_identity="voice-agent", stop=stop, timeout=20)
        )
        source, _, published = await _publish(agent, clip, name=f"checked-input-{repetition}")
        sources.append(source)
        stop.set()
        received = await capture
        assert published.published_pcm_sha256 == clip.pcm_sha256
        assert published.published_bytes == len(clip.pcm)
        assert received.publisher_identity == "voice-agent"
        output = tmp_path / f"received-{repetition}.wav"
        write_wav(output, received.pcm, sample_rate=received.sample_rate)
        with wave.open(str(output), "rb") as wav:
            assert wav.getnframes() > 0 and wav.getnchannels() == 1
    finally:
        await asyncio.gather(*(aclose_audio(source) for source in sources))
        await asyncio.gather(*(aclose_room(room) for room in (agent, player, decoy)))


async def test_timeout_and_cancellation_persist_failure_and_close_only_owned(tmp_path: Path):
    class Closer:
        def __init__(self):
            self.calls = 0

        async def close(self):
            self.calls += 1

    for cancellation in (False, True):
        owned = Closer()
        sentinel = Closer()
        path = tmp_path / f"failure-{cancellation}.jsonl"

        async def operation(_row, *, cancel=cancellation):
            if cancel:
                raise asyncio.CancelledError
            raise TimeoutError("no output")

        with pytest.raises((TimeoutError, asyncio.CancelledError)):
            await execute_with_evidence(operation, [owned.close], path, {"scenario": "affected"})
        row = json.loads(path.read_text().strip())
        assert row["completion"] == "failed"
        assert row["cleanup"]["complete"] is True
        assert owned.calls == 1
        assert sentinel.calls == 0


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
