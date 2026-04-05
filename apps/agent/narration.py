"""LLM narration generation for async activities using Anthropic SDK directly."""

import logging
import re
from typing import Any

from anthropic.types import ToolParam

from activity_templates import build_narration_prompt
from dialogue_parser import Segment
from llm_config import MODEL, extract_llm_text
from llm_config import client as _client
from voices import DEFAULT_VOICE, EMOTIONS

logger = logging.getLogger("divineruin.narration")

MAX_TOKENS = 500

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


def _build_narration_tool(npc_voice_ids: list[str]) -> ToolParam:
    """Build the tool schema for structured narration output.

    The character enum is constrained to DM_NARRATOR + the specific NPCs
    involved in this activity.
    """
    valid_characters = [DEFAULT_VOICE, *npc_voice_ids]

    return {
        "name": "narration_result",
        "description": "Submit the structured narration segments and a short UI summary.",
        "input_schema": {
            "type": "object",
            "required": ["segments", "summary"],
            "properties": {
                "segments": {
                    "type": "array",
                    "description": "Ordered narration segments. Each is one voice block.",
                    "items": {
                        "type": "object",
                        "required": ["character", "emotion", "text"],
                        "properties": {
                            "character": {
                                "type": "string",
                                "enum": valid_characters,
                                "description": "Voice character ID. DM_NARRATOR for narration, NPC voice ID for dialogue.",
                            },
                            "emotion": {
                                "type": "string",
                                "enum": EMOTIONS,
                                "description": "Emotional tone for this segment.",
                            },
                            "text": {
                                "type": "string",
                                "description": "The spoken text for this segment. No tags or brackets.",
                            },
                        },
                    },
                },
                "summary": {
                    "type": "string",
                    "description": "1-2 sentence plain-text summary of what happened (20-40 words). For the UI card, not audio.",
                },
            },
        },
    }


def _extract_tool_input(response: Any) -> dict[str, Any] | None:
    """Extract the tool input from an Anthropic tool_use response."""
    for block in response.content:
        if block.type == "tool_use" and block.name == "narration_result":
            return block.input
    return None


def _segments_to_text(segments: list[dict[str, str]]) -> str:
    """Concatenate segment text into a single plain-text narration."""
    return " ".join(seg["text"] for seg in segments)


def _segments_to_segment_objects(segments: list[dict[str, str]]) -> list[Segment]:
    """Convert raw dicts from tool output to Segment dataclass instances."""
    return [
        Segment(
            character=seg["character"],
            emotion=seg["emotion"],
            text=seg["text"],
        )
        for seg in segments
        if seg.get("text", "").strip()
    ]


async def generate_activity_narration(
    outcome: dict,
    player_data: dict,
    activity_data: dict,
) -> tuple[list[Segment], str, str]:
    """Generate structured narration for a resolved async activity.

    Uses Claude Haiku with tool_use for deterministic structured output.
    Returns (segments, narration_text, summary).
    """
    activity_type = activity_data.get("activity_type", "crafting")
    prompt, npc_voice_ids = build_narration_prompt(activity_type, outcome)
    tool = _build_narration_tool(npc_voice_ids)

    player_name = _sanitize_player_text(player_data.get("name", "the adventurer"))
    player_level = player_data.get("level", 1)
    player_class = _sanitize_player_text(player_data.get("class", "adventurer"))

    system_msg = (
        f"You narrate for a level {player_level} {player_class} named {player_name} "
        "in a dark fantasy world. Write for the ear: short sentences, concrete sensory details. "
        "60-120 words total across all segments. End with the decision point."
    )

    response = await _client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system_msg,
        tools=[tool],
        tool_choice={"type": "tool", "name": "narration_result"},
        messages=[{"role": "user", "content": prompt}],
    )

    logger.info(
        "Narration generated: %d input tokens, %d output tokens (model=%s)",
        response.usage.input_tokens,
        response.usage.output_tokens,
        MODEL,
    )

    tool_input = _extract_tool_input(response)
    if not tool_input or not tool_input.get("segments"):
        raise RuntimeError(f"LLM did not return valid narration segments: {response.content}")

    segments = _segments_to_segment_objects(tool_input["segments"])
    narration_text = _segments_to_text(tool_input["segments"])
    summary = tool_input.get("summary", "")

    logger.info("Narration: %d segments, %d chars, summary=%s", len(segments), len(narration_text), summary[:60])

    return segments, narration_text, summary
