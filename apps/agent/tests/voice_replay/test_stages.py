"""Stage timings let a slow replay row name the stage that was slow."""

from types import SimpleNamespace

import pytest
from livekit.agents.metrics import LLMMetrics, TTSMetrics

from voice_replay_stages import StageRecorder


def _llm_metrics(ttft: float, duration: float) -> LLMMetrics:
    return LLMMetrics(
        label="openai",
        request_id="r",
        timestamp=0.0,
        duration=duration,
        ttft=ttft,
        cancelled=False,
        completion_tokens=20,
        prompt_tokens=1000,
        prompt_cached_tokens=900,
        total_tokens=1020,
        tokens_per_second=10.0,
    )


def _tts_metrics(ttfb: float) -> TTSMetrics:
    return TTSMetrics(
        label="inworld",
        request_id="t",
        timestamp=0.0,
        ttfb=ttfb,
        duration=0.5,
        audio_duration=1.0,
        cancelled=False,
        characters_count=40,
        streamed=True,
    )


def _message(role: str, metrics: dict) -> SimpleNamespace:
    return SimpleNamespace(item=SimpleNamespace(role=role, metrics=metrics))


def test_stages_are_relative_to_source_speech_end():
    clock = iter([10.4, 11.0, 11.9, 12.1, 12.6])
    recorder = StageRecorder(now=lambda: next(clock))
    recorder.on_conversation_item(_message("user", {"transcription_delay": 0.3, "end_of_turn_delay": 0.4}))
    recorder.on_llm_metrics(_llm_metrics(ttft=0.45, duration=0.6))
    recorder.on_tools_executed(object())
    recorder.on_tts_metrics(_tts_metrics(ttfb=0.25))
    recorder.on_conversation_item(_message("assistant", {"llm_node_ttft": 0.5, "e2e_latency": 2.1}))

    stages = recorder.report(speech_end_monotonic=10.0)

    assert stages["user"] == [{"at_ms": pytest.approx(400), "transcription_delay_ms": 300, "end_of_turn_delay_ms": 400}]
    assert stages["llm_requests"] == [
        {
            "done_at_ms": pytest.approx(1000),
            "ttft_ms": 450,
            "duration_ms": 600,
            "prompt_tokens": 1000,
            "cached_tokens": 900,
            "completion_tokens": 20,
        }
    ]
    assert stages["tools_executed_at_ms"] == [pytest.approx(1900)]
    assert stages["tts_requests"] == [{"done_at_ms": pytest.approx(2100), "ttfb_ms": 250, "characters": 40}]
    assert stages["assistant"] == [{"at_ms": pytest.approx(2600), "llm_node_ttft_ms": 500, "e2e_latency_ms": 2100}]


def test_messages_without_metrics_are_not_recorded_as_stages():
    recorder = StageRecorder(now=lambda: 1.0)
    recorder.on_conversation_item(_message("assistant", {}))
    recorder.on_conversation_item(SimpleNamespace(item=SimpleNamespace(type="function_call")))

    assert recorder.report(speech_end_monotonic=0.0)["assistant"] == []


def _packet(data: bytes, topic: str) -> SimpleNamespace:
    return SimpleNamespace(data=data, topic=topic)


def test_game_events_reaching_the_player_are_timed_by_type():
    clock = iter([11.3, 11.4, 11.5])
    recorder = StageRecorder(now=lambda: next(clock))
    recorder.on_data_received(_packet(b'{"type": "dice_roll", "roll": 20}', "game_events"))
    recorder.on_data_received(_packet(b'{"type": "chat"}', "lk-chat-topic"))
    recorder.on_data_received(_packet(b"not json", "game_events"))

    assert recorder.report(speech_end_monotonic=10.0)["game_events"] == [
        {"at_ms": pytest.approx(1300), "type": "dice_roll"},
        {"at_ms": pytest.approx(1400), "type": "<unparseable>"},
    ]
