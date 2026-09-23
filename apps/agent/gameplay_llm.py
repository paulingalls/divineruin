"""Select the gameplay LLM without mixing provider-specific options."""

import os

from livekit.agents import llm
from livekit.plugins import anthropic, openai

LUNA_MODEL = "gpt-6-luna"
DEFAULT_GAMEPLAY_LLM = "openai-luna"
PROVIDER_API_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai-luna": "OPENAI_API_KEY",
}


def gameplay_llm_selection() -> str:
    selection = os.getenv("GAMEPLAY_LLM", DEFAULT_GAMEPLAY_LLM)
    if selection not in PROVIDER_API_KEYS:
        raise ValueError(f"Unsupported GAMEPLAY_LLM selection: {selection!r}")
    return selection


def gameplay_llm_api_key() -> str:
    return PROVIDER_API_KEYS[gameplay_llm_selection()]


def create_gameplay_llm(anthropic_model: str) -> llm.LLM:
    selection = gameplay_llm_selection()
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
        return openai.LLM(
            model=LUNA_MODEL,
            reasoning_effort="none",
            _strict_tool_schema=True,
        )
    raise AssertionError(f"Unhandled GAMEPLAY_LLM selection: {selection!r}")


def is_luna(selected: object) -> bool:
    return getattr(selected, "model", None) == LUNA_MODEL
