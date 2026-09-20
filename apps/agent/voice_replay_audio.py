from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from livekit import rtc


@dataclass(frozen=True)
class CheckedClip:
    path: Path
    transcript: str
    outcome_anchor: str
    model: str
    voice_id: str
    sample_rate: int
    channels: int
    sample_width_bytes: int
    samples: int
    silence_threshold: int
    final_voiced_sample: int
    sha256: str
    pcm_sha256: str
    pcm: bytes


@dataclass(frozen=True)
class ReceivedFrame:
    start_sample: int
    end_sample: int
    arrival_monotonic: float


@dataclass(frozen=True)
class PublishedAudio:
    speech_end_monotonic: float
    published_pcm_sha256: str
    published_bytes: int
    queue_size_ms: int
    max_queued_duration_ms: float


@dataclass(frozen=True)
class ReceivedAudio:
    pcm: bytes
    frames: list[ReceivedFrame]
    sample_rate: int
    channels: int
    publisher_identity: str
    track_sid: str


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def normalized_words(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+(?:[\'\u2019][a-z0-9]+)*", text.casefold())
    return [re.sub(r"[^a-z0-9]", "", token) for token in tokens]


def find_phrase(words: list[str], phrase: list[str]) -> int | None:
    """Index where `phrase` runs as whole words inside `words`, or None. The anchor-absence rule
    is asked of the manifest transcript and of the received-audio words; one tokenizer answers both,
    so a hyphenated or punctuated anchor cannot be absent on one side and present on the other."""
    if not phrase:
        return None
    return next((i for i in range(len(words) - len(phrase) + 1) if words[i : i + len(phrase)] == phrase), None)


def _require_int(entry: dict[str, Any], name: str) -> int:
    value = entry.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"manifest {name} must be an integer")
    return value


def load_checked_clip(clip_path: Path, manifest_path: Path | None = None) -> CheckedClip:
    manifest_path = manifest_path or clip_path.with_name("manifest.json")
    if not manifest_path.is_file():
        raise FileNotFoundError(f"voice replay manifest not found: {manifest_path}")
    if not clip_path.is_file():
        raise FileNotFoundError(f"voice replay clip not found: {clip_path}")
    try:
        manifest = json.loads(manifest_path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"voice replay manifest is invalid JSON: {manifest_path}") from exc
    clips = manifest.get("clips") if isinstance(manifest, dict) else None
    if not isinstance(clips, list) or len(clips) != 1 or not isinstance(clips[0], dict):
        raise ValueError("voice replay manifest must contain exactly one clip")
    entry = clips[0]
    if entry.get("filename") != clip_path.name:
        raise ValueError(f"manifest clip filename does not match {clip_path.name!r}")

    wav_bytes = clip_path.read_bytes()
    if _sha256(wav_bytes) != entry.get("sha256"):
        raise ValueError("voice replay WAV SHA256 does not match manifest")
    try:
        with wave.open(str(clip_path), "rb") as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            samples = wav.getnframes()
            compression = wav.getcomptype()
            pcm = wav.readframes(samples)
    except (wave.Error, EOFError) as exc:
        raise ValueError(f"voice replay clip is not a readable WAV: {clip_path}") from exc
    if compression != "NONE" or channels != 1 or sample_width != 2 or samples <= 0:
        raise ValueError("voice replay WAV must be nonempty PCM16 mono")
    expected = {
        "sample_rate": sample_rate,
        "channels": channels,
        "sample_width_bytes": sample_width,
        "samples": samples,
    }
    for name, actual in expected.items():
        if _require_int(entry, name) != actual:
            label = name.replace("_", " ")
            raise ValueError(f"voice replay {label} does not match manifest")
    if _sha256(pcm) != entry.get("pcm_sha256"):
        raise ValueError("voice replay PCM SHA256 does not match manifest")

    threshold = _require_int(entry, "silence_threshold")
    if threshold < 0:
        raise ValueError("voice replay silence threshold must be nonnegative")
    values = memoryview(pcm).cast("h")
    voiced = [index for index, sample in enumerate(values) if abs(sample) > threshold]
    if not voiced:
        raise ValueError("voice replay clip contains no voiced samples")
    if _require_int(entry, "final_voiced_sample") != voiced[-1]:
        raise ValueError("voice replay final voiced sample does not match PCM")

    transcript = entry.get("transcript")
    anchor = entry.get("outcome_anchor")
    model = entry.get("model")
    voice_id = entry.get("voice_id")
    if not all(isinstance(item, str) and item.strip() for item in (transcript, anchor, model, voice_id)):
        raise ValueError("voice replay transcript, anchor, model and voice id must be nonempty")
    anchor_words = normalized_words(anchor)
    if not anchor_words:
        raise ValueError("voice replay outcome anchor contains no words")
    if find_phrase(normalized_words(transcript), anchor_words) is not None:
        raise ValueError("voice replay outcome anchor must be absent from the input transcript")

    return CheckedClip(
        path=clip_path,
        transcript=transcript,
        outcome_anchor=anchor,
        model=model,
        voice_id=voice_id,
        sample_rate=sample_rate,
        channels=channels,
        sample_width_bytes=sample_width,
        samples=samples,
        silence_threshold=threshold,
        final_voiced_sample=voiced[-1],
        sha256=_sha256(wav_bytes),
        pcm_sha256=_sha256(pcm),
        pcm=pcm,
    )


def audio_frames(clip: CheckedClip, frame_ms: int = 20) -> list[rtc.AudioFrame]:
    samples_per_frame = clip.sample_rate * frame_ms // 1_000
    if samples_per_frame <= 0:
        raise ValueError("audio frame duration produced no samples")
    frame_bytes = samples_per_frame * clip.sample_width_bytes
    frames = []
    for offset in range(0, len(clip.pcm), frame_bytes):
        payload = clip.pcm[offset : offset + frame_bytes]
        if not payload:
            continue
        if len(payload) % clip.sample_width_bytes:
            raise ValueError("audio frame payload splits a PCM sample")
        frames.append(
            rtc.AudioFrame(
                data=payload,
                sample_rate=clip.sample_rate,
                num_channels=clip.channels,
                samples_per_channel=len(payload) // clip.sample_width_bytes,
            )
        )
    if not frames:
        raise ValueError("audio fixture produced no frames")
    return frames


async def publish_checked_audio(
    source: rtc.AudioSource,
    clip: CheckedClip,
    *,
    queue_size_ms: int,
    max_queue_ms: float,
    frame_sequence: list[rtc.AudioFrame] | None = None,
    clock: Any = time.perf_counter,
) -> PublishedAudio:
    payloads: list[bytes] = []
    max_queued = 0.0
    speech_end: float | None = None
    sample_cursor = 0
    for frame in frame_sequence if frame_sequence is not None else audio_frames(clip):
        queued = source.queued_duration
        max_queued = max(max_queued, queued)
        if queued * 1_000 > max_queue_ms:
            raise ValueError(f"audio source queue depth {queued * 1_000:.1f}ms exceeds {max_queue_ms:.1f}ms")
        captured_at = clock()
        await source.capture_frame(frame)
        payload = bytes(frame.data)
        payloads.append(payload)
        frame_end = sample_cursor + frame.samples_per_channel
        if sample_cursor <= clip.final_voiced_sample < frame_end:
            within_frame = (clip.final_voiced_sample + 1 - sample_cursor) / clip.sample_rate
            speech_end = captured_at + queued + within_frame
        sample_cursor = frame_end
    published = b"".join(payloads)
    if published != clip.pcm or speech_end is None:
        raise ValueError("published PCM bytes do not match the checked clip")
    await source.wait_for_playout()
    return PublishedAudio(
        speech_end_monotonic=speech_end,
        published_pcm_sha256=_sha256(published),
        published_bytes=len(published),
        queue_size_ms=queue_size_ms,
        max_queued_duration_ms=max_queued * 1_000,
    )


def write_wav(path: Path, pcm: bytes, *, sample_rate: int, channels: int = 1) -> str:
    if not pcm or len(pcm) % (channels * 2):
        raise ValueError("received PCM is empty or incomplete")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return _sha256(path.read_bytes())


def pcm_duration_seconds(pcm: bytes, sample_rate: int, channels: int = 1) -> float:
    samples = len(pcm) / (2 * channels)
    if not math.isfinite(samples) or samples <= 0:
        raise ValueError("PCM duration requires nonempty complete audio")
    return samples / sample_rate


async def close_room(room: rtc.Room) -> None:
    if room.isconnected():
        await room.disconnect()


async def close_source(source: rtc.AudioSource) -> None:
    source.clear_queue()
    await source.aclose()


async def cancel_task(task: asyncio.Task[Any]) -> None:
    if not task.done():
        task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def wait_for_output(
    session: Any, *, affected: bool, tool_events: list[Any], timeout: float, stable_seconds: float = 2.0
) -> None:
    deadline = time.monotonic() + timeout
    saw_speaking = False
    stable_since: float | None = None
    while time.monotonic() < deadline:
        state = session.agent_state
        saw_speaking = saw_speaking or state == "speaking"
        ready = saw_speaking and state == "listening" and (not affected or tool_events)
        stable_since = (stable_since or time.monotonic()) if ready else None
        if stable_since is not None and time.monotonic() - stable_since >= stable_seconds:
            return
        await asyncio.sleep(0.05)
    raise TimeoutError("agent produced no complete audible turn")


async def capture_received_audio(
    room: rtc.Room,
    *,
    publisher_identity: str,
    stop: asyncio.Event,
    sample_rate: int = 48_000,
    silence_tail_seconds: float = 0.75,
    timeout: float = 60.0,
) -> ReceivedAudio:
    matched: asyncio.Future[tuple[rtc.Track, rtc.RemoteTrackPublication, rtc.RemoteParticipant]] = (
        asyncio.get_running_loop().create_future()
    )

    def consider(track: rtc.Track, publication: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant) -> None:
        if (
            not matched.done()
            and participant.identity == publisher_identity
            and publication.kind == rtc.TrackKind.KIND_AUDIO
        ):
            matched.set_result((track, publication, participant))

    room.on("track_subscribed", consider)
    try:
        participant = room.remote_participants.get(publisher_identity)
        publication = next(
            (
                candidate
                for candidate in (participant.track_publications.values() if participant is not None else ())
                if candidate.kind == rtc.TrackKind.KIND_AUDIO and candidate.track is not None
            ),
            None,
        )
        if publication is not None:
            track = publication.track
        else:
            track, publication, _ = await asyncio.wait_for(matched, timeout)
    except TimeoutError as exc:
        raise TimeoutError(f"audio track from {publisher_identity!r} was not subscribed") from exc
    finally:
        room.off("track_subscribed", consider)
    stream = rtc.AudioStream(track, sample_rate=sample_rate, num_channels=1)
    iterator = stream.__aiter__()
    payloads: list[bytes] = []
    spans: list[ReceivedFrame] = []
    cursor = 0
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    try:
        while True:
            if stop.is_set() and payloads:
                break
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError("received audio did not complete before timeout")
            wait_for = min(remaining, silence_tail_seconds if stop.is_set() else remaining)
            try:
                event = await asyncio.wait_for(anext(iterator), timeout=wait_for)
            except StopAsyncIteration:
                break
            except TimeoutError:
                if stop.is_set():
                    break
                raise TimeoutError("expected publisher produced no audio frames") from None
            frame = event.frame
            if frame.sample_rate != sample_rate or frame.num_channels != 1:
                raise ValueError("received audio stream format drifted")
            payload = bytes(frame.data)
            if not payload:
                raise ValueError("received an empty audio frame")
            now = time.perf_counter()
            end = cursor + frame.samples_per_channel
            spans.append(ReceivedFrame(cursor, end, now))
            payloads.append(payload)
            cursor = end
    finally:
        await stream.aclose()
    pcm = b"".join(payloads)
    if not pcm or not spans:
        raise ValueError("expected publisher produced no received audio")
    return ReceivedAudio(
        pcm=pcm,
        frames=spans,
        sample_rate=sample_rate,
        channels=1,
        publisher_identity=publisher_identity,
        track_sid=publication.sid,
    )
