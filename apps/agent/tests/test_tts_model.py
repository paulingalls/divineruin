"""Behavior checks for the Inworld model selected by both speech paths."""

import base64
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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


class _FixedClock:
    """Stands in for tts_prerender's ``time``: every measured interval is ``step``.

    Replaces the module attribute rather than ``time.perf_counter`` itself, which
    would mutate the stdlib clock for everything else sharing the process.
    """

    def __init__(self, step: float) -> None:
        self._step = step
        self._now = 0.0

    def perf_counter(self) -> float:
        now = self._now
        self._now += self._step
        return now


@pytest.mark.asyncio
async def test_smoke_covers_every_markup_tag_with_factual_output(monkeypatch, capsys):
    monkeypatch.setitem(VOICES, "DM_NARRATOR", "narrator-voice")
    monkeypatch.setenv("INWORLD_API_KEY", "sentinel-secret")
    calls = []

    async def synthesize(text, voice, *, speaking_rate=1.0, session=None):
        calls.append((text, voice, speaking_rate, session))
        return f"audio-{len(calls)}".encode()

    facts = {"codec": "mp3", "duration_seconds": 0.4, "sample_rate_hertz": 44100, "channels": 1}
    decoded = []

    def decode(audio):
        decoded.append(audio)
        return facts

    with (
        patch.object(tts_prerender, "inworld_tts", synthesize),
        patch.object(tts_prerender, "_decode_audio", side_effect=decode),
        patch.object(tts_prerender, "time", _FixedClock(step=0.1)),
    ):
        await tts_prerender.run_tts2_smoke()

    tags = sorted({markup for markup in INWORLD_MARKUPS.values() if markup})
    assert tags, "voices.INWORLD_MARKUPS carries no markup tag for the smoke to submit"

    submitted = [call[0] for call in calls]
    neutral = get_voice_config("DM_NARRATOR", "neutral")
    assert calls[0] == (tts_prerender.SMOKE_NEUTRAL_TEXT, neutral.voice, neutral.speaking_rate, None)
    assert submitted[1:] == [apply_markup(tts_prerender.SMOKE_MARKED_TEXT, tag) for tag in tags]
    for (_text, voice, rate, session), tag in zip(calls[1:], tags, strict=True):
        emotion = next(e for e, markup in INWORLD_MARKUPS.items() if markup == tag)
        config = get_voice_config("DM_NARRATOR", emotion)
        assert (voice, rate, session) == (config.voice, config.speaking_rate, None)
    assert decoded == [f"audio-{i}".encode() for i in range(1, len(calls) + 1)]

    output = capsys.readouterr().out
    records = [json.loads(line) for line in output.splitlines()]
    labels = ["neutral"] + [f"marked:{tag}" for tag in tags]
    assert len(records) == len(labels) + 1
    for record, label, text, audio in zip(records[:-1], labels, submitted, decoded, strict=True):
        assert record == {
            "audio_bytes": len(audio),
            "characters": len(text),
            "decoder": facts,
            "elapsed_ms": 100.0,
            "estimated_usd": len(text) * 25 / 1_000_000,
            "model": "inworld-tts-2",
            "sample": label,
        }
    total_characters = sum(len(text) for text in submitted)
    assert records[-1] == {
        "audio_bytes": sum(len(audio) for audio in decoded),
        "characters": total_characters,
        "decoder": {"decoded_samples": len(labels)},
        "elapsed_ms": round(100.0 * len(labels), 3),
        "estimated_usd": total_characters * 25 / 1_000_000,
        "model": "inworld-tts-2",
        "sample": "total",
    }
    assert "sentinel-secret" not in output


def test_smoke_refuses_a_corpus_with_no_markup_tags(monkeypatch):
    monkeypatch.setattr(tts_prerender, "INWORLD_MARKUPS", dict.fromkeys(INWORLD_MARKUPS, ""))
    with pytest.raises(RuntimeError, match="No nonempty Inworld emotion markup"):
        tts_prerender._smoke_samples()


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
    run = MagicMock()
    with patch.object(tts_prerender, "asyncio", SimpleNamespace(run=run)):
        with pytest.raises(SystemExit):
            tts_prerender.main(argv)
    run.assert_not_called()
