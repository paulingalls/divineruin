"""Behavior checks for the Inworld model selected by both speech paths."""

import base64
import json
from unittest.mock import patch

import pytest
from livekit.plugins import inworld

import tts_prerender
from base_agent import _make_tts
from tts_prerender import inworld_tts
from voices import INWORLD_MARKUPS, VOICES, apply_markup, get_voice_config


def test_livekit_default_voice_uses_tts2_and_preserves_defaults():
    with patch.dict("os.environ", {"INWORLD_API_KEY": "test-key"}):
        expected = inworld.TTS(speaking_rate=1.0)
        actual = _make_tts(speaking_rate=1.0)

    assert actual.model == "inworld-tts-2"
    assert actual._opts.voice == expected._opts.voice
    assert actual._opts.speaking_rate == 1.0


def test_livekit_character_voice_uses_tts2_and_preserves_voice_and_rate():
    with patch.dict("os.environ", {"INWORLD_API_KEY": "test-key"}):
        actual = _make_tts(voice="character-voice", speaking_rate=0.85)

    assert actual.model == "inworld-tts-2"
    assert actual._opts.voice == "character-voice"
    assert actual._opts.speaking_rate == 0.85


class _StreamingContent:
    def __aiter__(self):
        async def lines():
            encoded = base64.b64encode(b"audio").decode()
            yield f'{{"result": {{"audioContent": "{encoded}"}}}}\n'.encode()

        return lines()


class _Response:
    status = 200
    content = _StreamingContent()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


class _Session:
    def post(self, url, **kwargs):
        self.url = url
        self.kwargs = kwargs
        return _Response()


@pytest.mark.asyncio
async def test_rest_request_uses_tts2_and_preserves_voice_rate_and_format():
    session = _Session()
    with patch.dict("os.environ", {"INWORLD_API_KEY": "test-key"}):
        audio = await inworld_tts(
            "A test line.",
            "rest-voice",
            speaking_rate=0.87,
            session=session,
        )

    assert audio == b"audio"
    assert session.kwargs["json"] == {
        "text": "A test line.",
        "voiceId": "rest-voice",
        "modelId": "inworld-tts-2",
        "audioConfig": {
            "audioEncoding": "MP3",
            "sampleRateHertz": 44100,
            "bitrate": 128000,
            "speakingRate": 0.87,
        },
    }


@pytest.mark.asyncio
async def test_smoke_synthesizes_neutral_and_current_markup_with_factual_output(monkeypatch, capsys):
    monkeypatch.setitem(VOICES, "DM_NARRATOR", "narrator-voice")
    monkeypatch.setenv("INWORLD_API_KEY", "sentinel-secret")
    calls = []

    async def synthesize(text, voice, *, speaking_rate=1.0, session=None):
        calls.append((text, voice, speaking_rate, session))
        return f"audio-{len(calls)}".encode()

    decoder_facts = [
        {"codec": "mp3", "duration_seconds": 0.4, "sample_rate_hertz": 44100, "channels": 1},
        {"codec": "mp3", "duration_seconds": 0.6, "sample_rate_hertz": 44100, "channels": 1},
    ]
    decoded = []

    def decode(audio):
        decoded.append(audio)
        return len(audio), decoder_facts[len(decoded) - 1]

    with (
        patch.object(tts_prerender, "inworld_tts", synthesize),
        patch.object(tts_prerender, "_decode_audio", side_effect=decode),
        patch.object(tts_prerender.time, "perf_counter", side_effect=[1.0, 1.1, 2.0, 2.25]),
    ):
        await tts_prerender.run_tts2_smoke()

    nonempty_emotion = next(emotion for emotion, markup in INWORLD_MARKUPS.items() if markup)
    neutral = get_voice_config("DM_NARRATOR", "neutral")
    marked = get_voice_config("DM_NARRATOR", nonempty_emotion)
    assert calls == [
        (tts_prerender.SMOKE_NEUTRAL_TEXT, neutral.voice, neutral.speaking_rate, None),
        (
            apply_markup(tts_prerender.SMOKE_MARKED_TEXT, marked.inworld_markup),
            marked.voice,
            marked.speaking_rate,
            None,
        ),
    ]
    assert decoded == [b"audio-1", b"audio-2"]

    output = capsys.readouterr().out
    records = [json.loads(line) for line in output.splitlines()]
    submitted = [call[0] for call in calls]
    expected_characters = [len(text) for text in submitted]
    assert records == [
        {
            "audio_bytes": 7,
            "characters": expected_characters[0],
            "decoder": decoder_facts[0],
            "elapsed_ms": 100.0,
            "estimated_usd": expected_characters[0] * 25 / 1_000_000,
            "model": "inworld-tts-2",
            "sample": "neutral",
        },
        {
            "audio_bytes": 7,
            "characters": expected_characters[1],
            "decoder": decoder_facts[1],
            "elapsed_ms": 250.0,
            "estimated_usd": expected_characters[1] * 25 / 1_000_000,
            "model": "inworld-tts-2",
            "sample": "marked",
        },
        {
            "audio_bytes": 14,
            "characters": sum(expected_characters),
            "decoder": {"decoded_samples": 2},
            "elapsed_ms": 350.0,
            "estimated_usd": sum(expected_characters) * 25 / 1_000_000,
            "model": "inworld-tts-2",
            "sample": "total",
        },
    ]
    assert "sentinel-secret" not in output


@pytest.mark.asyncio
async def test_smoke_propagates_provider_failure(monkeypatch):
    monkeypatch.setitem(VOICES, "DM_NARRATOR", "narrator-voice")

    async def fail(*_args, **_kwargs):
        raise RuntimeError("provider refused request")

    with patch.object(tts_prerender, "inworld_tts", fail):
        with pytest.raises(RuntimeError, match="provider refused"):
            await tts_prerender.run_tts2_smoke()


@pytest.mark.asyncio
async def test_smoke_rejects_empty_audio(monkeypatch):
    monkeypatch.setitem(VOICES, "DM_NARRATOR", "narrator-voice")

    async def empty(*_args, **_kwargs):
        return b""

    with patch.object(tts_prerender, "inworld_tts", empty):
        with pytest.raises(RuntimeError, match="returned no audio"):
            await tts_prerender.run_tts2_smoke()


def test_decoder_rejects_invalid_audio():
    with pytest.raises(RuntimeError, match="ffprobe"):
        tts_prerender._decode_audio(b"not an audio stream")


@pytest.mark.parametrize("argv", [[], ["--unknown"]])
def test_cli_rejects_missing_or_unknown_smoke_flag(argv):
    with patch.object(tts_prerender.asyncio, "run") as run:
        with pytest.raises(SystemExit):
            tts_prerender.main(argv)
    run.assert_not_called()
