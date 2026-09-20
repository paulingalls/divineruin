from __future__ import annotations

import hashlib
import json
import wave
from pathlib import Path

import pytest

from voice_replay_audio import ReceivedFrame, audio_frames, load_checked_clip, publish_checked_audio
from voice_replay_metrics import TranscribedWord, compute_audio_metrics, validate_timing_row


def _write_wav(path: Path, samples: list[int], sample_rate: int = 1_000) -> bytes:
    pcm = b"".join(sample.to_bytes(2, "little", signed=True) for sample in samples)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return pcm


def _fixture(tmp_path: Path, *, transcript: str = "Please gather herbs", final_voiced_sample: int = 2):
    clip = tmp_path / "gather_herbs.wav"
    pcm = _write_wav(clip, [0, 20, -30, 0, 0])
    entry = {
        "filename": clip.name,
        "transcript": transcript,
        "outcome_anchor": "quality wood",
        "model": "inworld-tts-2",
        "voice_id": "test-voice",
        "sample_rate": 1_000,
        "channels": 1,
        "sample_width_bytes": 2,
        "samples": 5,
        "silence_threshold": 10,
        "final_voiced_sample": final_voiced_sample,
        "sha256": hashlib.sha256(clip.read_bytes()).hexdigest(),
        "pcm_sha256": hashlib.sha256(pcm).hexdigest(),
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"clips": [entry]}))
    return clip, manifest, entry


def test_checked_clip_loads_closed_manifest(tmp_path: Path):
    clip, manifest, entry = _fixture(tmp_path)
    loaded = load_checked_clip(clip, manifest)

    assert loaded.transcript == entry["transcript"]
    assert loaded.pcm_sha256 == entry["pcm_sha256"]
    assert loaded.final_voiced_sample == 2


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda manifest, clip, entry: manifest.unlink(), "manifest"),
        (lambda manifest, clip, entry: clip.unlink(), "clip"),
        (lambda manifest, clip, entry: manifest.write_text('{"clips": []}'), "exactly one"),
        (
            lambda manifest, clip, entry: manifest.write_text(json.dumps({"clips": [entry, entry]})),
            "exactly one",
        ),
        (lambda manifest, clip, entry: clip.write_bytes(clip.read_bytes() + b"x"), "SHA256"),
        (
            lambda manifest, clip, entry: manifest.write_text(
                json.dumps({"clips": [{**entry, "pcm_sha256": "0" * 64}]})
            ),
            "PCM SHA256",
        ),
        (
            lambda manifest, clip, entry: manifest.write_text(json.dumps({"clips": [{**entry, "sample_rate": 999}]})),
            "sample rate",
        ),
        (
            lambda manifest, clip, entry: manifest.write_text(
                json.dumps({"clips": [{**entry, "final_voiced_sample": 1}]})
            ),
            "final voiced",
        ),
        (
            lambda manifest, clip, entry: manifest.write_text(
                json.dumps({"clips": [{**entry, "transcript": "Find quality wood"}]})
            ),
            "anchor",
        ),
    ],
)
def test_checked_clip_rejects_contract_drift(tmp_path: Path, mutation, match: str):
    clip, manifest, entry = _fixture(tmp_path)
    mutation(manifest, clip, entry)
    with pytest.raises((FileNotFoundError, ValueError), match=match):
        load_checked_clip(clip, manifest)


async def test_publisher_endpoint_includes_prequeue_depth_and_rejects_changed_bytes(tmp_path: Path):
    clip_path, manifest, _ = _fixture(tmp_path)
    clip = load_checked_clip(clip_path, manifest)

    class Source:
        queued_duration = 0.05

        async def capture_frame(self, frame):
            pass

        async def wait_for_playout(self):
            pass

    published = await publish_checked_audio(Source(), clip, queue_size_ms=100, max_queue_ms=100, clock=lambda: 10.0)
    assert published.speech_end_monotonic == pytest.approx(10.053)

    with pytest.raises(ValueError, match="published PCM"):
        await publish_checked_audio(
            Source(),
            clip,
            queue_size_ms=100,
            max_queue_ms=100,
            frame_sequence=audio_frames(clip)[:-1],
        )

    Source.queued_duration = 0.2
    with pytest.raises(ValueError, match="queue depth"):
        await publish_checked_audio(Source(), clip, queue_size_ms=100, max_queue_ms=100)


def _frames() -> list[ReceivedFrame]:
    return [
        ReceivedFrame(0, 500, 11.0),
        ReceivedFrame(500, 600, 11.5),
        ReceivedFrame(600, 1_000, 12.2),
        ReceivedFrame(1_000, 1_500, 12.6),
    ]


def _words() -> list[TranscribedWord]:
    return [
        TranscribedWord("I", 0.10, 0.20),
        TranscribedWord("found", 0.30, 0.45),
        TranscribedWord("quality", 0.65, 0.82),
        TranscribedWord("wood", 0.84, 0.98),
    ]


def _pcm() -> bytes:
    samples = [0] * 1_500
    for start, end in ((100, 200), (300, 450), (650, 820), (840, 980)):
        samples[start:end] = [100] * (end - start)
    return b"".join(sample.to_bytes(2, "little", signed=True) for sample in samples)


def test_metrics_use_received_frame_clock_and_audio_words():
    result = compute_audio_metrics(
        pcm=_pcm(),
        sample_rate=1_000,
        frames=_frames(),
        words=_words(),
        source_speech_end_monotonic=10.0,
        silence_threshold=10,
        outcome_anchor="quality wood",
        input_transcript="Please gather herbs",
        model_text="quality wood appeared earlier in model text",
    )

    assert result.first_meaningful_word == "I"
    assert result.first_meaningful_latency_ms == pytest.approx(1_100)
    assert result.outcome_latency_ms == pytest.approx(2_250)
    assert result.pre_outcome_words == ["I", "found"]


@pytest.mark.parametrize(
    ("words", "frames", "pcm", "source_end", "match"),
    [
        ([], _frames(), _pcm(), 10.0, "words"),
        (_words(), [], _pcm(), 10.0, "frames"),
        ([*_words()[:2], TranscribedWord("quality", 1.6, 1.7), _words()[3]], _frames(), _pcm(), 10.0, "range"),
        ([TranscribedWord("I", 0.0, 0.0), *_words()[1:]], _frames(), _pcm(), 10.0, "window"),
        (_words(), _frames(), b"\0" * len(_pcm()), 10.0, "silent"),
        (_words(), _frames(), b"d\0" * 1_500, 10.0, "boundary"),
        (_words()[:2], _frames(), _pcm(), 10.0, "anchor"),
        (_words(), [ReceivedFrame(0, 500, 11.0), ReceivedFrame(600, 1_500, 11.6)], _pcm(), 10.0, "contiguous"),
        (_words(), _frames(), _pcm(), 12.0, "negative"),
    ],
)
def test_metrics_fail_loud_on_unusable_evidence(words, frames, pcm, source_end: float, match: str):
    with pytest.raises(ValueError, match=match):
        compute_audio_metrics(
            pcm=pcm,
            sample_rate=1_000,
            frames=frames,
            words=words,
            source_speech_end_monotonic=source_end,
            silence_threshold=10,
            outcome_anchor="quality wood",
            input_transcript="Please gather herbs",
        )


def test_anchor_needs_nonempty_pre_result_floor_and_audio_not_model_text():
    with pytest.raises(ValueError, match="pre-result"):
        compute_audio_metrics(
            pcm=_pcm(),
            sample_rate=1_000,
            frames=_frames(),
            words=_words()[2:],
            source_speech_end_monotonic=10.0,
            silence_threshold=10,
            outcome_anchor="quality wood",
            input_transcript="Please gather herbs",
        )
    with pytest.raises(ValueError, match="anchor"):
        compute_audio_metrics(
            pcm=_pcm(),
            sample_rate=1_000,
            frames=_frames(),
            words=_words()[:2],
            source_speech_end_monotonic=10.0,
            silence_threshold=10,
            outcome_anchor="quality wood",
            input_transcript="Please gather herbs",
            model_text="quality wood",
        )


def _valid_row(scenario: str = "affected") -> dict:
    row = {
        "completion": "success",
        "scenario": scenario,
        "repetition": 0,
        "temperature": "cold",
        "source_audio": {"sha256": "a", "pcm_sha256": "b", "published_pcm_sha256": "b"},
        "received_audio": {"path": "received.wav", "sha256": "c", "bytes": 100},
        "provider_usage": {
            "stt": {"provider": "deepgram", "model": "nova-3", "units": 1},
            "llm": {"provider": "openai", "model": "gpt-5.6-luna", "units": 1},
            "tts": {"provider": "inworld", "model": "inworld-tts-2", "units": 1},
            "analysis_stt": {"provider": "deepgram", "model": "nova-3", "units": 1},
        },
        "tool_count": 1,
        "tool_names": ["check"],
        "state_before": {"inventory": {"herb": 2}},
        "state_after": {"inventory": {"herb": 2, "quality_wood": 1}},
        "state_delta": {"quality_wood": 2},
        "tool_output": {"materials": ["quality_wood", "quality_wood"]},
        "metrics": {"first_meaningful_latency_ms": 100, "outcome_latency_ms": 200},
        "cleanup": {"complete": True},
    }
    if scenario == "direct":
        row.update(tool_count=0, tool_names=[], state_after=row["state_before"], state_delta={})
        row["metrics"] = {"first_meaningful_latency_ms": 100}
    return row


def test_timing_row_requires_complete_usage_audio_tools_and_state():
    validate_timing_row(_valid_row())
    validate_timing_row(_valid_row("direct"))

    for path in (
        ("received_audio", "bytes"),
        ("provider_usage", "stt"),
        ("provider_usage", "llm"),
        ("provider_usage", "tts"),
        ("provider_usage", "analysis_stt"),
    ):
        broken = _valid_row()
        del broken[path[0]][path[1]]
        with pytest.raises(ValueError):
            validate_timing_row(broken)


def test_timing_row_rejects_duplicate_or_missing_grant_and_direct_mutation():
    for delta in ({}, {"quality_wood": 4}):
        broken = _valid_row()
        broken["state_delta"] = delta
        with pytest.raises(ValueError, match="quality_wood"):
            validate_timing_row(broken)

    direct = _valid_row("direct")
    direct["tool_count"] = 1
    with pytest.raises(ValueError, match="direct"):
        validate_timing_row(direct)


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda row: row.update(temperature="warm"), "labelled cold"),
        (lambda row: row["source_audio"].update(published_pcm_sha256="wrong"), "PCM hashes"),
        (lambda row: row["provider_usage"]["tts"].update(units=0), "nonzero tts"),
        (lambda row: row.update(completion=""), "completion"),
        (lambda row: row["cleanup"].update(complete=False), "cleanup"),
    ],
)
def test_timing_row_rejects_incomplete_labels_usage_and_cleanup(mutation, match: str):
    row = _valid_row()
    mutation(row)
    with pytest.raises(ValueError, match=match):
        validate_timing_row(row)
