"""Narration crosses the Python write and Bun HTTP boundaries with local defaults."""

import os
import subprocess
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

from tests.acceptance._server import start_server

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("configured", [None, ""])
def test_host_narration_is_served_with_default_media(monkeypatch, configured):
    for key in ("MEDIA_DIR", "ASYNC_AUDIO_DIR", "ASSET_IMAGE_DIR"):
        monkeypatch.delenv(key, raising=False)
    if configured is not None:
        monkeypatch.setenv("MEDIA_DIR", configured)
    monkeypatch.setenv("AGENT_ENV", "development")
    filename = "media_" + uuid.uuid4().hex + ".mp3"
    code = """
import asyncio
from pathlib import Path
from llm_config import AUDIO_DIR, audio_url_for
from tts_prerender import synthesize_to_file, _generate_mp3_silence
async def synthesize(text, voice):
    return _generate_mp3_silence(0.1)
path = Path(AUDIO_DIR) / FILENAME
asyncio.run(synthesize_to_file("A road.", "test", str(path), synthesize=synthesize))
print(str(path))
print(audio_url_for(FILENAME))
""".replace("FILENAME", repr(filename))
    try:
        with contextmanager(start_server)(os.environ["DATABASE_URL"]) as server:
            result = subprocess.run(
                [sys.executable, "-c", code], cwd=ROOT / "apps/agent", capture_output=True, text=True, check=True
            )
            path, url = result.stdout.strip().splitlines()[-2:]
            response = httpx.get(server["base_url"] + url)
            assert response.status_code == 200
            assert response.content == Path(path).read_bytes() and response.content
    finally:
        (ROOT / "assets/generated/audio" / filename).unlink(missing_ok=True)


def test_relative_media_dir_is_refused_by_both_processes(monkeypatch):
    """A relative root resolves against each process's own cwd, splitting writes from reads."""
    env = dict(os.environ, MEDIA_DIR="assets/generated", AGENT_ENV="development")
    python = subprocess.run(
        [sys.executable, "-c", "from media_dir import media_dir; media_dir()"],
        cwd=ROOT / "apps/agent",
        env=env,
        capture_output=True,
        text=True,
    )
    bun = subprocess.run(
        ["bun", "-e", 'import { mediaDir } from "./src/media-dir.ts"; mediaDir();'],
        cwd=ROOT / "apps/server",
        env=env,
        capture_output=True,
        text=True,
    )
    for result in (python, bun):
        assert result.returncode != 0
        assert "MEDIA_DIR must be an absolute path" in result.stderr
