from __future__ import annotations

import re
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any

from voice_replay_audio import ReceivedFrame


@dataclass(frozen=True)
class TranscribedWord:
    text: str
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class AudioMetrics:
    first_meaningful_word: str
    first_meaningful_latency_ms: float
    outcome_latency_ms: float | None
    pre_outcome_words: list[str]
    outcome_words: list[str]
    result_boundary_sample: int | None


def normalized_words(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+(?:['’][a-z0-9]+)*", text.casefold())
    return [re.sub(r"[^a-z0-9]", "", token) for token in tokens]


def _sample_window(word: TranscribedWord, sample_rate: int, sample_count: int) -> tuple[int, int]:
    if word.start_seconds < 0 or word.end_seconds <= word.start_seconds:
        raise ValueError(f"transcribed word {word.text!r} has an invalid window")
    start = round(word.start_seconds * sample_rate)
    end = round(word.end_seconds * sample_rate)
    if start < 0 or end > sample_count:
        raise ValueError(f"transcribed word {word.text!r} is outside the received audio range")
    if end <= start:
        raise ValueError(f"transcribed word {word.text!r} has a zero-length window")
    return start, end


def _received_time(sample: int, frames: list[ReceivedFrame], sample_rate: int) -> float:
    for frame in frames:
        if frame.start_sample <= sample < frame.end_sample:
            return frame.arrival_monotonic + (sample - frame.start_sample) / sample_rate
    raise ValueError(f"word onset sample {sample} is outside received frame spans")


def _validate_frames(frames: list[ReceivedFrame], sample_count: int) -> None:
    if not frames:
        raise ValueError("received audio has no frames")
    cursor = 0
    prior_time = float("-inf")
    for frame in frames:
        if frame.start_sample != cursor or frame.end_sample <= frame.start_sample:
            raise ValueError("received frame spans must be contiguous and nonempty")
        if frame.arrival_monotonic < prior_time:
            raise ValueError("received frame arrival times must be monotonic")
        cursor = frame.end_sample
        prior_time = frame.arrival_monotonic
    if cursor != sample_count:
        raise ValueError("received frame spans do not cover the PCM sample range")


def _window_is_voiced(pcm_samples: memoryview, start: int, end: int, threshold: int) -> bool:
    return any(abs(sample) > threshold for sample in pcm_samples[start:end])


def compute_audio_metrics(
    *,
    pcm: bytes,
    sample_rate: int,
    frames: list[ReceivedFrame],
    words: list[TranscribedWord],
    source_speech_end_monotonic: float,
    silence_threshold: int,
    outcome_anchor: str | None,
    input_transcript: str,
    min_result_gap_seconds: float = 0.2,
) -> AudioMetrics:
    if not pcm or len(pcm) % 2:
        raise ValueError("received PCM is empty or incomplete")
    if sample_rate <= 0:
        raise ValueError("sample rate must be positive")
    if not words:
        raise ValueError("Deepgram returned no received-audio words")
    pcm_samples = memoryview(pcm).cast("h")
    _validate_frames(frames, len(pcm_samples))
    starts: list[int] = []
    ends: list[int] = []
    word_tokens: list[str] = []
    for word in words:
        start, end = _sample_window(word, sample_rate, len(pcm_samples))
        if not _window_is_voiced(pcm_samples, start, end, silence_threshold):
            raise ValueError(f"transcribed word {word.text!r} maps to a silent audio window")
        tokens = normalized_words(word.text)
        if len(tokens) != 1:
            raise ValueError(f"transcribed word {word.text!r} does not normalize to one word")
        starts.append(start)
        ends.append(end)
        word_tokens.append(tokens[0])
    if starts != sorted(starts):
        raise ValueError("transcribed word timestamps are not monotonic")

    first_time = _received_time(starts[0], frames, sample_rate)
    first_latency = (first_time - source_speech_end_monotonic) * 1_000
    if first_latency < 0:
        raise ValueError("received-audio latency is negative")
    if outcome_anchor is None:
        return AudioMetrics(words[0].text, first_latency, None, [], [], None)
    anchor = normalized_words(outcome_anchor)
    if not anchor:
        raise ValueError("outcome anchor contains no words")
    input_words = normalized_words(input_transcript)
    if any(input_words[i : i + len(anchor)] == anchor for i in range(len(input_words) - len(anchor) + 1)):
        raise ValueError("outcome anchor is present in the input transcript")

    anchor_index = next(
        (i for i in range(len(word_tokens) - len(anchor) + 1) if word_tokens[i : i + len(anchor)] == anchor),
        None,
    )
    if anchor_index is None:
        raise ValueError(f"outcome anchor {outcome_anchor!r} is missing from received audio words")
    anchor_sample = starts[anchor_index]
    minimum_gap = round(min_result_gap_seconds * sample_rate)
    gaps: list[tuple[int, int, int]] = []
    silence_start: int | None = None
    for sample in range(ends[0], anchor_sample):
        silent = abs(pcm_samples[sample]) <= silence_threshold
        if silent and silence_start is None:
            silence_start = sample
        elif not silent and silence_start is not None:
            if sample - silence_start >= minimum_gap:
                gaps.append((sample - silence_start, silence_start, sample))
            silence_start = None
    if silence_start is not None and anchor_sample - silence_start >= minimum_gap:
        gaps.append((anchor_sample - silence_start, silence_start, anchor_sample))
    if not gaps:
        raise ValueError("received audio has no pre-result speech boundary before the outcome anchor")
    _, gap_start, boundary_sample = max(gaps)
    pre_count = sum(start < gap_start for start in starts)

    outcome_time = _received_time(anchor_sample, frames, sample_rate)
    outcome_latency = (outcome_time - source_speech_end_monotonic) * 1_000
    if outcome_latency < 0:
        raise ValueError("received-audio latency is negative")
    return AudioMetrics(
        first_meaningful_word=words[0].text,
        first_meaningful_latency_ms=first_latency,
        outcome_latency_ms=outcome_latency,
        pre_outcome_words=[word.text for word in words[:pre_count]],
        outcome_words=[word.text for word in words[anchor_index : anchor_index + len(anchor)]],
        result_boundary_sample=boundary_sample,
    )


def summarize_provider_usage(
    session_usage: list[Any],
    tts_metrics: list[Any],
    analysis_metrics: list[Any],
    *,
    luna_model: str,
    inworld_model: str,
) -> dict[str, Any]:
    stt = [item for item in session_usage if getattr(item, "type", "") == "stt_usage"]
    llm = [item for item in session_usage if getattr(item, "type", "") == "llm_usage"]
    if not stt or not llm or not tts_metrics or not analysis_metrics:
        raise ValueError("STT, Luna LLM, Inworld TTS and analysis STT usage must all be nonempty")

    def record(item: Any) -> dict[str, Any]:
        if is_dataclass(item):
            return asdict(item)
        if callable(dump := getattr(item, "model_dump", None)):
            return dump()
        raise TypeError(f"unsupported provider usage type: {type(item).__name__}")

    def usage(provider: str, model: str, items: list[Any], unit: str, field: str) -> dict[str, Any]:
        records = list(map(record, items))
        return {
            "provider": provider,
            "model": model,
            "unit": unit,
            "units": sum(float(item.get(field, 0)) for item in records),
            "records": records,
        }

    return {
        "stt": usage("deepgram", "nova-3", stt, "seconds", "audio_duration"),
        "llm": usage("openai", luna_model, llm, "output_tokens", "output_tokens"),
        "tts": usage("inworld", inworld_model, tts_metrics, "characters", "characters_count"),
        "analysis_stt": usage("deepgram", "nova-3", analysis_metrics, "seconds", "audio_duration"),
    }


def _required_mapping(row: dict[str, Any], name: str) -> dict[str, Any]:
    value = row.get(name)
    if not isinstance(value, dict):
        raise ValueError(f"timing row requires {name}")
    return value


def validate_timing_row(row: dict[str, Any]) -> None:
    if row.get("completion") not in {"success", "failed"}:
        raise ValueError("timing row requires a completion state")
    scenario = row.get("scenario")
    if scenario not in {"affected", "direct"}:
        raise ValueError("timing row requires an affected or direct scenario")
    repetition = row.get("repetition")
    if not isinstance(repetition, int) or repetition < 0:
        raise ValueError("timing row requires a nonnegative repetition")
    expected_temperature = "cold" if repetition == 0 else "warm"
    if row.get("temperature") != expected_temperature:
        raise ValueError(f"timing row repetition {repetition} must be labelled {expected_temperature}")

    source = _required_mapping(row, "source_audio")
    if not source.get("pcm_sha256") or source.get("published_pcm_sha256") != source.get("pcm_sha256"):
        raise ValueError("source audio requires matching checked and published PCM hashes")
    received = _required_mapping(row, "received_audio")
    if not received.get("path") or not received.get("sha256") or received.get("bytes", 0) <= 0:
        raise ValueError("timing row requires nonempty received audio")
    usage = _required_mapping(row, "provider_usage")
    expected_usage = {
        "stt": ("deepgram", "nova-3"),
        "llm": ("openai", "gpt-5.6-luna"),
        "tts": ("inworld", "inworld-tts-2"),
        "analysis_stt": ("deepgram", "nova-3"),
    }
    for name, (provider, model) in expected_usage.items():
        item = usage.get(name)
        if not isinstance(item, dict) or item.get("provider") != provider or item.get("model") != model:
            raise ValueError(f"timing row requires {name} usage from {provider} {model}")
        if item.get("units", 0) <= 0:
            raise ValueError(f"timing row requires nonzero {name} usage")
    if not _required_mapping(row, "cleanup").get("complete"):
        raise ValueError("timing row cleanup is incomplete")

    tool_count = row.get("tool_count")
    names = row.get("tool_names")
    before = _required_mapping(row, "state_before")
    after = _required_mapping(row, "state_after")
    delta = _required_mapping(row, "state_delta")
    metrics = _required_mapping(row, "metrics")
    if metrics.get("first_meaningful_latency_ms") is None:
        raise ValueError("timing row requires first meaningful speech latency")
    if scenario == "affected":
        if tool_count != 1 or names != ["check"]:
            raise ValueError("affected timing row requires exactly one check tool")
        output = _required_mapping(row, "tool_output")
        materials = output.get("materials")
        if not isinstance(materials, list) or not materials or any(not isinstance(item, str) for item in materials):
            raise ValueError("affected timing row requires the gather tool material multiset")
        expected_delta = {item: materials.count(item) for item in set(materials)}
        if delta != expected_delta or delta.get("quality_wood", 0) <= 0:
            raise ValueError("affected timing row state delta must equal the quality_wood tool result")
        if metrics.get("outcome_latency_ms") is None:
            raise ValueError("affected timing row requires audible outcome latency")
    elif tool_count != 0 or names != [] or before != after or delta:
        raise ValueError("direct timing row must have no tools or state mutation")
