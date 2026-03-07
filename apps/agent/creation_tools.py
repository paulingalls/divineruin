"""Character creation tools for the DM agent.

Three tools for the creation flow: push visual cards, record choices, finalize.
"""

from __future__ import annotations

import json
import logging
import re

from livekit.agents.llm import function_tool
from livekit.agents.voice import RunContext

import db
from creation_data import CLASSES, DEITIES, RACES
from creation_rules import build_character_data, infer_culture
from game_events import publish_game_event
from session_data import SessionData

logger = logging.getLogger("divineruin.creation")

VALID_CARD_CATEGORIES = {"race", "class", "deity"}
VALID_CHOICE_CATEGORIES = {"race", "class", "deity", "name", "backstory"}

# --- Input sanitization ---
_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9 '\-]")
MAX_NAME_LENGTH = 50
MAX_BACKSTORY_LENGTH = 500


def _sanitize_name(value: str) -> str:
    """Strip unsafe characters and cap length for character names."""
    return _SAFE_NAME_RE.sub("", value)[:MAX_NAME_LENGTH].strip()


def _sanitize_backstory(value: str) -> str:
    """Strip control characters and cap length for backstory text."""
    # Allow letters, digits, common punctuation, spaces
    cleaned = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", value)
    return cleaned[:MAX_BACKSTORY_LENGTH].strip()


def _safe_id_snippet(value: str) -> str:
    """Truncate and sanitize an ID for inclusion in error messages."""
    return re.sub(r"[^a-zA-Z0-9_\-]", "", value[:32])


@function_tool
async def push_creation_cards(
    context: RunContext,
    category: str,
) -> str:
    """Push visual cards to client and return full data for narration.

    Args:
        category: One of "race", "class", or "deity".
    """
    if category not in VALID_CARD_CATEGORIES:
        return json.dumps({"error": f"Invalid category: {category}. Use: race, class, or deity."})

    sd: SessionData = context.userdata

    if category == "race":
        items = RACES
        cards = [
            {"id": r.id, "title": r.name, "description": r.card_description, "category": "race"} for r in items.values()
        ]
        full_data = [{"id": r.id, "name": r.name, "description": r.description} for r in items.values()]
    elif category == "class":
        items = CLASSES
        cards = [
            {"id": c.id, "title": c.name, "description": c.card_description, "category": "class"}
            for c in items.values()
        ]
        full_data = [
            {"id": c.id, "name": c.name, "category": c.category, "description": c.description} for c in items.values()
        ]
    else:  # deity
        items = DEITIES
        cards = [
            {
                "id": d.id,
                "title": f"{d.name}, {d.title}" if d.id != "none" else d.name,
                "description": d.card_description,
                "category": "deity",
            }
            for d in items.values()
        ]
        full_data = [
            {"id": d.id, "name": d.name, "title": d.title, "domain": d.domain, "description": d.description}
            for d in items.values()
        ]

    # Publish cards to client
    await publish_game_event(sd.room, "creation_cards", {"cards": cards}, sd.event_bus)

    return json.dumps({"category": category, "count": len(full_data), "options": full_data})


@function_tool
async def set_creation_choice(
    context: RunContext,
    category: str,
    value: str,
) -> str:
    """Record a creation choice after player confirms.

    Args:
        category: One of "race", "class", "deity", "name", or "backstory".
        value: ID for race/class/deity, free text for name/backstory.
    """
    if category not in VALID_CHOICE_CATEGORIES:
        return json.dumps({"error": f"Invalid category: {category}."})

    sd: SessionData = context.userdata
    cs = sd.creation_state
    if cs is None or cs.phase == "complete":
        return json.dumps({"error": "Not in creation mode."})

    # Validate ID-based choices
    if category == "race":
        if value not in RACES:
            return json.dumps({"error": f"Unknown race: {_safe_id_snippet(value)}. Valid: {', '.join(RACES.keys())}"})
        cs.race = value
        cs.phase = "calling"
    elif category == "class":
        if value not in CLASSES:
            return json.dumps(
                {"error": f"Unknown class: {_safe_id_snippet(value)}. Valid: {', '.join(CLASSES.keys())}"}
            )
        cs.class_choice = value
        cs.phase = "devotion"
    elif category == "deity":
        if value not in DEITIES:
            return json.dumps(
                {"error": f"Unknown deity: {_safe_id_snippet(value)}. Valid: {', '.join(DEITIES.keys())}"}
            )
        cs.deity = value
        cs.phase = "identity"
    elif category == "name":
        sanitized = _sanitize_name(value)
        if not sanitized:
            return json.dumps({"error": "Name cannot be empty."})
        cs.name = sanitized
    elif category == "backstory":
        cs.backstory = _sanitize_backstory(value) if value else ""

    # Publish visual feedback
    await publish_game_event(
        sd.room,
        "creation_card_selected",
        {"category": category, "value": value},
        sd.event_bus,
    )

    # Clear cards after selection (with brief delay handled client-side)
    await publish_game_event(sd.room, "creation_cards", {"cards": []}, sd.event_bus)

    # Build progress summary
    progress = {
        "race": cs.race,
        "class": cs.class_choice,
        "deity": cs.deity,
        "name": cs.name,
        "backstory": cs.backstory is not None,
        "phase": cs.phase,
    }

    # Guidance for next step
    remaining = []
    if cs.race is None:
        remaining.append("race")
    if cs.class_choice is None:
        remaining.append("class")
    if cs.deity is None:
        remaining.append("deity")
    if cs.name is None:
        remaining.append("name")
    if cs.backstory is None:
        remaining.append("backstory")

    guidance = f"Remaining: {', '.join(remaining)}." if remaining else "All choices made. Call finalize_character."

    # Return the stored value (sanitized for name/backstory) rather than raw input
    stored_value = value
    if category == "name":
        stored_value = cs.name or ""
    elif category == "backstory":
        stored_value = cs.backstory or ""

    return json.dumps({"confirmed": category, "value": stored_value, "progress": progress, "guidance": guidance})


@function_tool
async def finalize_character(context: RunContext) -> str:
    """Generate stats and persist completed character.

    Call when all creation choices are set (race, class, deity, name, backstory).
    """
    sd: SessionData = context.userdata
    cs = sd.creation_state
    if cs is None or cs.phase == "complete":
        return json.dumps({"error": "Not in creation mode."})

    # Validate all required fields
    missing = []
    if cs.race is None:
        missing.append("race")
    if cs.class_choice is None:
        missing.append("class")
    if cs.name is None:
        missing.append("name")
    if missing:
        return json.dumps({"error": f"Missing required choices: {', '.join(missing)}"})

    # Deity can be None (deferred) or "none" (explicitly no patron)
    deity_id = cs.deity

    try:
        character_data = build_character_data(
            name=cs.name,
            race_id=cs.race,
            class_id=cs.class_choice,
            deity_id=deity_id,
            backstory=cs.backstory or "",
        )
    except ValueError:
        logger.exception("Invalid character data for %s", sd.player_id)
        return json.dumps({"error": "Invalid character data. Please check your choices."})

    # Persist to DB
    try:
        await db.create_player(sd.player_id, None, character_data)
    except Exception:
        logger.exception("Failed to create player %s", sd.player_id)
        return json.dumps({"error": "Failed to save character. Please try again."})

    # Update session state
    sd.location_id = character_data["location_id"]
    cs.phase = "complete"

    # Publish session_init so client gets character data
    try:
        payload = await db.get_session_init_payload(sd.player_id)
        await publish_game_event(sd.room, "session_init", payload, sd.event_bus)
    except Exception:
        logger.exception("Failed to publish session_init after creation")

    # Build summary for DM narration
    cultures = infer_culture(cs.race, cs.class_choice, deity_id)
    culture_name = cultures[0].replace("_", " ").title() if cultures else "unknown"
    deity_name = DEITIES[deity_id].name if deity_id and deity_id in DEITIES else "no patron"
    race_name = RACES[cs.race].name if cs.race in RACES else cs.race
    class_name = CLASSES[cs.class_choice].name if cs.class_choice in CLASSES else cs.class_choice

    summary = {
        "character": {
            "name": cs.name,
            "race": race_name,
            "class": class_name,
            "deity": deity_name,
            "culture": culture_name,
            "location": character_data["location_id"],
            "hp": character_data["hp"],
            "ac": character_data["ac"],
        },
        "instruction": (
            "The character is complete. Narrate the transition from creation into the world. "
            "The mist clears, identity solidifies, and the player finds themselves at their "
            "starting location. Keep it to two vivid sentences. Then begin the first scene."
        ),
    }
    return json.dumps(summary)
