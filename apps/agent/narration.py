"""LLM narration generation for async activities using Anthropic SDK directly."""

import logging
import re

import anthropic

from activity_templates import build_narration_prompt

logger = logging.getLogger("divineruin.narration")

# Claude Haiku for cost-effective narration
MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 300

_client = anthropic.AsyncAnthropic()

_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9 '\-]")
MAX_NAME_LENGTH = 30


def _sanitize_player_text(value: str, max_len: int = MAX_NAME_LENGTH) -> str:
    """Strip non-alphanumeric characters and cap length to prevent prompt injection."""
    return _SAFE_NAME_RE.sub("", value)[:max_len].strip() or "the adventurer"


async def generate_activity_narration(
    outcome: dict,
    player_data: dict,
    activity_data: dict,
) -> str:
    """Generate narration text for a resolved async activity.

    Uses Claude Haiku for cost efficiency. Returns narration text with dialogue tags.
    """
    activity_type = activity_data.get("activity_type", "crafting")
    prompt = build_narration_prompt(activity_type, outcome, activity_data)

    player_name = _sanitize_player_text(player_data.get("name", "the adventurer"))
    player_level = player_data.get("level", 1)
    player_class = _sanitize_player_text(player_data.get("class", "adventurer"))

    system_msg = (
        f"You narrate for a level {player_level} {player_class} named {player_name} "
        "in a dark fantasy world. Write for the ear: short sentences, concrete sensory details. "
        "60-120 words. End with the decision point. Use dialogue tags [NPC:Name] and [NARRATOR]."
    )

    response = await _client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system_msg,
        messages=[{"role": "user", "content": prompt}],
    )

    narration = response.content[0].text

    # Log token usage for cost tracking
    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    logger.info(
        "Narration generated: %d input tokens, %d output tokens (model=%s)",
        input_tokens,
        output_tokens,
        MODEL,
    )

    return narration
