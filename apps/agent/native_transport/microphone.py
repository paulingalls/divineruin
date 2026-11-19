import asyncio
from collections.abc import Callable

from acceptance._livekit_client import wait_for_audio_track
from acceptance.choir_acoustic_source import AcousticSource
from livekit import rtc


async def receive_marker(
    room: rtc.Room, identity: str, run_id: str, report_frames: Callable[[int], None]
) -> tuple[int, dict[str, str | int]]:
    track = await wait_for_audio_track(room, identity=identity, timeout=20)
    publications = room.remote_participants[identity].track_publications.values()
    if not any(p.track is track and p.source == rtc.TrackSource.SOURCE_MICROPHONE for p in publications):
        raise RuntimeError(f"{identity} did not publish a native microphone track")
    source = AcousticSource(run_id)
    peak = 0
    stream = rtc.AudioStream(track, sample_rate=48000, num_channels=1, frame_size_ms=20)
    try:
        async with asyncio.timeout(25):
            async for event in stream:
                frame = event.frame
                if frame.sample_rate != 48000 or frame.num_channels != 1:
                    raise RuntimeError("native microphone must deliver 48 kHz mono PCM")
                marker = source.observe(frame.data, frame.sample_rate)
                peak = max(peak, source.last_peak)
                report_frames(source.frames)
                if marker is not None:
                    return source.frames, {**marker, "identity": identity}
    except TimeoutError as error:
        raise RuntimeError(
            f"native microphone did not decode current run {run_id} marker "
            f"after {source.frames} frames, symbols={source.observed_symbols}, "
            f"purity={source.max_purity:.3f}, peak={peak}"
        ) from error
    finally:
        await stream.aclose()
    raise RuntimeError("native microphone stream ended before the current marker")
