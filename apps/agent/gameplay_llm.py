"""Select the gameplay LLM without mixing provider-specific options."""

import os
from weakref import WeakSet

from livekit.agents import llm
from livekit.plugins import anthropic, openai

LUNA_MODEL = "gpt-5.6-luna"
_LUNA_PILOTS: WeakSet[llm.LLM] = WeakSet()


def create_gameplay_llm(anthropic_model: str) -> llm.LLM:
    selection = os.getenv("GAMEPLAY_LLM", "anthropic")
    if selection == "anthropic":
        # Anthropic rejects three full profiles on aggregate compiled-grammar limits;
        # ADR 0008 records why its production route remains strict-off.
        return anthropic.LLM(
            model=anthropic_model,
            temperature=0.8,
            caching="ephemeral",
            _strict_tool_schema=False,
        )
    if selection == "openai-luna":
        selected = openai.LLM(
            model=LUNA_MODEL,
            reasoning_effort="none",
            _strict_tool_schema=True,
        )
        _LUNA_PILOTS.add(selected)
        return selected
    raise ValueError(f"Unsupported GAMEPLAY_LLM selection: {selection!r}")


def is_luna_pilot(selected: object) -> bool:
    return selected in _LUNA_PILOTS
