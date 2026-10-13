import base64
import json
from unittest.mock import patch

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from livekit.plugins import inworld

import tts_prerender
from base_agent import _make_tts
from tts_prerender import inworld_tts


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


@pytest.mark.asyncio
async def test_rest_request_uses_tts2_and_preserves_voice_rate_and_format(monkeypatch):
    """A real aiohttp server exercises the vendor NDJSON response contract without inventing it."""
    received: dict[str, object] = {}

    async def handler(request: web.Request) -> web.StreamResponse:
        received["body"] = await request.json()
        received["authorization"] = request.headers["Authorization"]
        response = web.StreamResponse()
        await response.prepare(request)
        encoded = base64.b64encode(b"audio").decode()
        await response.write(json.dumps({"result": {"audioContent": encoded}}).encode() + b"\n")
        await response.write_eof()
        return response

    app = web.Application()
    app.router.add_post("/tts/v1/voice:stream", handler)
    server = TestServer(app)
    await server.start_server()
    monkeypatch.setattr(tts_prerender, "INWORLD_BASE_URL", str(server.make_url("")).rstrip("/"))
    monkeypatch.setenv("INWORLD_API_KEY", "test-key")
    try:
        async with aiohttp.ClientSession() as session:
            audio = await inworld_tts(
                "A test line.",
                "rest-voice",
                speaking_rate=0.87,
                session=session,
            )
    finally:
        await server.close()

    assert audio == b"audio"
    assert received["authorization"] == "Basic test-key"
    assert received["body"] == {
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
