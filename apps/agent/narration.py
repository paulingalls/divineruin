"""LLM narration generation for async activities using Anthropic SDK directly."""

import logging
import re

from activity_templates import build_narration_prompt
from llm_config import MODEL, extract_llm_text
from llm_config import client as _client

logger = logging.getLogger("divineruin.narration")

MAX_TOKENS = 300

_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9 '\-]")
MAX_NAME_LENGTH = 30


def _sanitize_player_text(value: str, max_len: int = MAX_NAME_LENGTH) -> str:
    """Strip non-alphanumeric characters and cap length to prevent prompt injection."""
    return _SAFE_NAME_RE.sub("", value)[:max_len].strip() or "the adventurer"


async def generate_progress_snippets(
    activity_data: dict,
    player_data: dict,
) -> list[str]:
    """Generate 2-3 short intermediate progress lines for an in-flight activity.

    Uses Claude Haiku for cost efficiency. Returns list of 15-30 word snippets
    describing progressive stages of the activity.
    """
    activity_type = activity_data.get("activity_type", "crafting")
    parameters = activity_data.get("parameters", {})

    player_name = _sanitize_player_text(player_data.get("name", "the adventurer"))

    if activity_type == "crafting":
        item_name = _sanitize_player_text(parameters.get("result_item_name", "an item"), max_len=50)
        context = f"crafting {item_name} at the forge"
    elif activity_type == "training":
        stat = _sanitize_player_text(parameters.get("stat", "combat"), max_len=20)
        context = f"training {stat} with their mentor"
    else:
        errand_type = _sanitize_player_text(parameters.get("errand_type", "scouting"), max_len=20)
        destination = _sanitize_player_text(parameters.get("destination", "the area"), max_len=30)
        context = f"companion on a {errand_type} errand to {destination}"

    system_msg = (
        "You write terse progress updates for a fantasy RPG activity. "
        "Each line is 15-30 words, present tense, sensory. No dialogue tags. "
        "Write for the ear."
    )

    prompt = (
        f"{player_name} is {context}. "
        "Write exactly 3 short progress lines representing early, middle, and late stages. "
        "One line per stage. No numbering, no bullets."
    )

    response = await _client.messages.create(
        model=MODEL,
        max_tokens=200,
        system=system_msg,
        messages=[{"role": "user", "content": prompt}],
    )

    text = extract_llm_text(response)
    lines = [line.strip() for line in text.split("\n") if line.strip()]

    logger.info(
        "Progress snippets generated: %d input tokens, %d output tokens",
        response.usage.input_tokens,
        response.usage.output_tokens,
    )

    return lines[:3] if len(lines) > 3 else lines


async def generate_notification_hook(
    narration_text: str,
    activity_type: str,
) -> str:
    """Generate a short push notification hook from narration text.

    Returns a 10-20 word teaser suitable for a push notification.
    If narration is short enough, returns its first sentence directly.
    """
    # Try extracting first sentence directly for short narrations
    clean = re.sub(r"\[(?:NPC:[^\]]*|NARRATOR)\]\s*", "", narration_text)
    sentences = [s.strip() for s in re.split(r"[.!?]+", clean) if s.strip()]
    if sentences and len(sentences[0].split()) <= 20:
        return sentences[0] + "."

    system_msg = (
        "You write ultra-short push notification hooks for a fantasy RPG. "
        "10-20 words max. Intriguing, no spoilers, makes the player want to open the app."
    )

    response = await _client.messages.create(
        model=MODEL,
        max_tokens=50,
        system=system_msg,
        messages=[
            {
                "role": "user",
                "content": f"Activity type: {activity_type}\nFull narration:\n{narration_text}\n\nWrite a single notification hook line.",
            }
        ],
    )

    hook = extract_llm_text(response)
    logger.info(
        "Notification hook generated: %d input tokens, %d output tokens",
        response.usage.input_tokens,
        response.usage.output_tokens,
    )
    return hook


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

    narration = extract_llm_text(response)

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
