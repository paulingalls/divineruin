"""Shared LLM client, model, and audio config for agent modules."""

import os

import anthropic

MODEL = "claude-haiku-4-5-20251001"

AUDIO_DIR = os.environ.get(
    "ASYNC_AUDIO_DIR",
    os.path.join(os.path.dirname(__file__), "..", "server", "audio"),
)

client = anthropic.AsyncAnthropic()


def audio_url_for(filename: str) -> str:
    """Build the public URL path for an audio file."""
    return f"/api/audio/{filename}"
