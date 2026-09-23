"""The checked-clip contract, audio-derived timing, and the timing row's completeness contract."""

from __future__ import annotations

import hashlib
import json
import wave
from pathlib import Path

import pytest
from livekit.agents.metrics import LLMModelUsage, STTMetrics, STTModelUsage, TTSMetrics
from livekit.agents.metrics.base import Metadata

from gameplay_llm import LUNA_MODEL
from voice_replay_audio import (
    ReceivedFrame,
    audio_frames,
    load_checked_clip,
    publish_checked_audio,
    write_wav,
)
from voice_replay_metrics import TranscribedWord, compute_audio_metrics, summarize_provider_usage, validate_timing_row


def test_voice_replay_scope_names_the_production_latency_it_excludes():
    from multiplayer_transcription import COMPLETE_UTTERANCE_ENDPOINTING_SECONDS
    from voice_replay_scope import REPLAY_ENDPOINTING_SECONDS, VOICE_REPLAY_SCOPE

    assert VOICE_REPLAY_SCOPE["production_gameplay_equivalent"] is False
    # Both sides read their live source, not a transcribed copy: a scope block that restated
    # the two numbers would keep publishing 0.5-vs-1.0 after either one moved.
    assert VOICE_REPLAY_SCOPE["input_endpointing_seconds"] == REPLAY_ENDPOINTING_SECONDS
    assert VOICE_REPLAY_SCOPE["production_endpointing_seconds"] == COMPLETE_UTTERANCE_ENDPOINTING_SECONDS
    assert REPLAY_ENDPOINTING_SECONDS < COMPLETE_UTTERANCE_ENDPOINTING_SECONDS
    assert VOICE_REPLAY_SCOPE["excluded_production_stages"] == [
        "multi_participant_transcriber_queue",
        "multiplayer_input_serialization",
    ]


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


def _reclip(manifest: Path, clip: Path, entry: dict, *, samples: list[int], channels: int = 1, width: int = 2):
    pcm = b"".join(sample.to_bytes(width, "little", signed=True) for sample in samples)
    with wave.open(str(clip), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(width)
        wav.setframerate(1_000)
        wav.writeframes(pcm)
    rewritten = {
        **entry,
        "channels": channels,
        "sample_width_bytes": width,
        "samples": len(samples) // channels,
        "sha256": hashlib.sha256(clip.read_bytes()).hexdigest(),
        "pcm_sha256": hashlib.sha256(pcm).hexdigest(),
    }
    manifest.write_text(json.dumps({"clips": [rewritten]}))


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
        (
            lambda manifest, clip, entry: manifest.write_text(
                json.dumps({"clips": [{**entry, "filename": "other.wav"}]})
            ),
            "filename does not match",
        ),
        (lambda manifest, clip, entry: manifest.write_text("{not json"), "invalid JSON"),
        (
            lambda manifest, clip, entry: manifest.write_text(json.dumps({"clips": [{**entry, "transcript": "   "}]})),
            "must be nonempty",
        ),
        (
            lambda manifest, clip, entry: manifest.write_text(
                json.dumps({"clips": [{**entry, "outcome_anchor": "!!!"}]})
            ),
            "anchor contains no words",
        ),
        (
            lambda manifest, clip, entry: manifest.write_text(
                json.dumps({"clips": [{**entry, "silence_threshold": -1}]})
            ),
            "threshold must be nonnegative",
        ),
        # a replaced clip: same manifest contract, different audio shape
        (
            lambda manifest, clip, entry: _reclip(manifest, clip, entry, samples=[0, 20, -30, 0, 0, 0], channels=2),
            "PCM16 mono",
        ),
        (
            lambda manifest, clip, entry: _reclip(manifest, clip, entry, samples=[0, 0, 0, 0, 0]),
            "no voiced samples",
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


@pytest.mark.parametrize("pcm", [b"", b"\0" * 3])
def test_received_wav_refuses_empty_or_truncated_pcm(tmp_path: Path, pcm: bytes):
    with pytest.raises(ValueError, match="empty or incomplete"):
        write_wav(tmp_path / "received.wav", pcm, sample_rate=48_000)


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


def _measure(**override):
    """compute_audio_metrics over the shared received-audio fixture, with `override` swapped in."""
    return compute_audio_metrics(
        **{
            "pcm": _pcm(),
            "sample_rate": 1_000,
            "frames": _frames(),
            "words": _words(),
            "source_speech_end_monotonic": 10.0,
            "silence_threshold": 10,
            "outcome_anchor": "quality wood",
            "input_transcript": "Please gather herbs",
            **override,
        }
    )


def test_metrics_use_received_frame_clock_and_audio_words():
    result = _measure()

    assert result.first_meaningful_word == "I"
    assert result.first_meaningful_latency_ms == pytest.approx(1_100)
    assert result.outcome_latency_ms == pytest.approx(2_250)
    assert result.pre_outcome_words == ["I", "found"]
    assert result.outcome_words == ["quality", "wood"]
    assert result.result_boundary_sample == 650


def test_pre_result_words_include_a_word_that_overlaps_the_silence_boundary():
    words = [*_words()]
    words[1] = TranscribedWord("found", 0.30, 0.55)
    result = _measure(words=words)

    assert result.pre_outcome_words == ["I", "found"]


def _session_usage() -> list:
    return [
        STTModelUsage(provider="Deepgram", model="nova-3", audio_duration=5.0),
        LLMModelUsage(
            provider="api.openai.com",
            model=LUNA_MODEL,
            input_tokens=1_000,
            input_cached_tokens=750,
            output_tokens=30,
        ),
    ]


def _tts_metrics(model: str | None = "inworld-tts-2") -> list:
    return [
        TTSMetrics(
            label="inworld",
            request_id="tts-1",
            timestamp=1.0,
            ttfb=0.1,
            duration=0.2,
            audio_duration=2.0,
            cancelled=False,
            characters_count=42,
            streamed=False,
            metadata=Metadata(model_name=model, model_provider="Inworld") if model else None,
        )
    ]


def _analysis_metrics() -> list:
    return [
        STTMetrics(
            label="deepgram",
            request_id="stt-1",
            timestamp=2.0,
            duration=0.2,
            audio_duration=3.0,
            streamed=False,
            metadata=Metadata(model_name="nova-3", model_provider="Deepgram"),
        )
    ]


def test_provider_usage_keeps_billable_counts_from_livekit_models():
    usage = summarize_provider_usage(
        _session_usage(),
        _tts_metrics(),
        _analysis_metrics(),
        luna_model=LUNA_MODEL,
        inworld_model="inworld-tts-2",
    )

    assert usage["llm"]["records"][0]["input_tokens"] == 1_000
    assert usage["llm"]["records"][0]["input_cached_tokens"] == 750
    assert usage["llm"]["records"][0]["output_tokens"] == 30
    assert usage["tts"]["records"][0]["characters_count"] == 42
    assert usage["tts"]["units"] == 42


@pytest.mark.parametrize("spoken", [None, "inworld-tts-1"])
def test_row_model_is_the_model_the_provider_named_not_the_configured_constant(spoken):
    """The card's whole TTS-2 claim rests on this field, so it must come off the wire: a run that
    speaks another model, or names none, cannot be labelled inworld-tts-2."""
    with pytest.raises(ValueError, match="not the pinned 'inworld-tts-2'"):
        summarize_provider_usage(
            _session_usage(),
            _tts_metrics(spoken),
            _analysis_metrics(),
            luna_model=LUNA_MODEL,
            inworld_model="inworld-tts-2",
        )


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
        ([_words()[0], _words()[2], _words()[1], _words()[3]], _frames(), _pcm(), 10.0, "not monotonic"),
        (
            _words(),
            [ReceivedFrame(0, 500, 11.0), ReceivedFrame(500, 600, 10.5), ReceivedFrame(600, 1_500, 12.2)],
            _pcm(),
            10.0,
            "arrival times must be monotonic",
        ),
        (
            _words(),
            [ReceivedFrame(0, 500, 11.0), ReceivedFrame(500, 600, 11.5), ReceivedFrame(600, 1_000, 12.2)],
            _pcm(),
            10.0,
            "do not cover",
        ),
        ([*_words()[:2], TranscribedWord("quality wood", 0.65, 0.98)], _frames(), _pcm(), 10.0, "one word"),
        (_words(), _frames(), b"", 10.0, "empty or incomplete"),
        (_words(), _frames(), _pcm() + b"\0", 10.0, "empty or incomplete"),
    ],
)
def test_metrics_fail_loud_on_unusable_evidence(words, frames, pcm, source_end: float, match: str):
    with pytest.raises(ValueError, match=match):
        _measure(words=words, frames=frames, pcm=pcm, source_speech_end_monotonic=source_end)


def test_metrics_reject_an_unusable_sample_rate_and_a_wordless_anchor():
    for override, match in (({"sample_rate": 0}, "sample rate"), ({"outcome_anchor": "!!!"}, "anchor contains no")):
        with pytest.raises(ValueError, match=match):
            _measure(**override)


def test_anchor_must_follow_a_pre_result_pause_and_stay_out_of_the_input():
    # The anchor opening the received audio leaves no pre-result speech to separate it from.
    with pytest.raises(ValueError, match="no pre-result speech boundary"):
        _measure(words=_words()[2:])
    with pytest.raises(ValueError, match="present in the input transcript"):
        _measure(input_transcript="Please find quality wood")


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
            "llm": {"provider": "openai", "model": LUNA_MODEL, "units": 1},
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


def test_timing_row_rejects_previous_luna_model():
    row = _valid_row()
    row["provider_usage"]["llm"]["model"] = "gpt-5.6-luna"
    with pytest.raises(ValueError, match="requires llm usage"):
        validate_timing_row(row)


def test_timing_row_accepts_the_model_a_comparison_run_selected():
    row = _valid_row()
    row["provider_usage"]["llm"]["model"] = "gpt-5.6-luna"
    validate_timing_row(row, luna_model="gpt-5.6-luna")
    with pytest.raises(ValueError, match="requires llm usage"):
        validate_timing_row(_valid_row(), luna_model="gpt-5.6-luna")


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
        (lambda row: row.update(scenario="other"), "affected or direct"),
        (lambda row: row.update(repetition=-1), "nonnegative repetition"),
        (lambda row: row.update(tool_count=2, tool_names=["check", "check"]), "exactly one check"),
        (lambda row: row.update(tool_names=["stage"]), "exactly one check"),
        (lambda row: row["tool_output"].update(materials=[]), "material multiset"),
        (lambda row: row["metrics"].pop("outcome_latency_ms"), "audible outcome latency"),
        (lambda row: row["metrics"].pop("first_meaningful_latency_ms"), "first meaningful speech"),
        # a gather that granted something else entirely still has a self-consistent delta
        (
            lambda row: row.update(state_delta={"oak_wood": 2}, tool_output={"materials": ["oak_wood"] * 2}),
            "quality_wood tool result",
        ),
    ],
)
def test_timing_row_rejects_incomplete_labels_usage_and_cleanup(mutation, match: str):
    row = _valid_row()
    mutation(row)
    with pytest.raises(ValueError, match=match):
        validate_timing_row(row)
