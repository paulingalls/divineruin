"""Shared LLM client, model, and audio config for agent modules."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import anthropic

if TYPE_CHECKING:
    import anthropic.types

MODEL = "claude-haiku-4-5-20251001"

# Anthropic's three strict-schema ceilings, verbatim from the API 400s probed for
# ADR 0008. livekit-plugins-anthropic defaults _strict_tool_schema=True, so every
# registered @function_tool counts, and all three are PER REQUEST, not per tool.
# tests/test_strict_tool_budget.py walks every agent's emitted schema against them.
#
# "The maximum number of strict tools supported is 20" (ADR 0004).
MAX_STRICT_TOOLS = 20
# "Schemas contains too many parameters with union types (N parameters with type
# arrays or anyOf). This causes exponential compilation cost... (limit: 16 parameters
# with unions)". An `anyOf` of N kind-tagged variants costs ONE -- that is the whole
# mechanism ADR 0008 rests on.
MAX_UNION_PARAMS = 16
# "Schema is too complex." -- a separate per-object cliff. 12 nullables in one object
# is accepted; 14 is not. Cap at the last measured-good value.
MAX_NULLABLE_PER_OBJECT = 12

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
