"""Shared LLM client, model, and audio config for agent modules."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import anthropic

if TYPE_CHECKING:
    import anthropic.types

MODEL = "claude-haiku-4-5-20251001"

AUDIO_DIR = os.environ.get(
    "ASYNC_AUDIO_DIR",
    os.path.join(os.path.dirname(__file__), "..", "server", "audio"),
)

client = anthropic.AsyncAnthropic()


def audio_url_for(filename: str) -> str:
    """Build the public URL path for an audio file."""
    return f"/api/audio/{filename}"


def extract_llm_text(response: anthropic.types.Message) -> str:
    """Extract text from the first text content block in an Anthropic response.

    Returns empty string if no text block is found.
    """
    for block in response.content:
        if block.type == "text":
            return block.text.strip()
    return ""
