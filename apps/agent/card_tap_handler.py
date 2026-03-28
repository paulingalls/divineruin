"""Handler for client card-tap hints during character creation.

When a player taps a creation card on the mobile client, a data channel
message arrives on the "player_hints" topic. This module receives those
messages, looks up the full description from creation_data, and asks the
agent to narrate it and confirm the choice.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

from livekit import rtc
from livekit.agents import AgentSession

import event_types as E
from creation_data import CLASSES, DEITIES, RACES
from session_data import SessionData

logger = logging.getLogger("divineruin.card_tap")

HINT_COOLDOWN_S = 2.0
PLAYER_HINTS_TOPIC = "player_hints"


def build_hint_instruction(card_id: str, category: str) -> str | None:
    """Build an instruction for the agent to narrate a tapped card.

    Returns None if the card_id/category is invalid.
    Uses the full ``description`` field (ear-first narration text).
    """
    if category == "race" and card_id in RACES:
        item = RACES[card_id]
        return (
            f"The player is interested in the {item.name}. "
            f"Describe what it feels like to be a {item.name} using this detail: {item.description} "
            "Keep it to two vivid sentences. Then ask if this is what they feel."
        )
    elif category == "class" and card_id in CLASSES:
        item = CLASSES[card_id]
        return (
            f"The player is interested in the {item.name} ({item.category}). "
            f"Describe the {item.name} using this detail: {item.description} "
            "Keep it to two vivid sentences. Then ask if this is their calling."
        )
    elif category == "deity" and card_id in DEITIES:
        item = DEITIES[card_id]
        if card_id == "none":
            return (
                "The player is considering walking without a patron. "
                f"Describe: {item.description} "
                "Keep it to two sentences. Ask if they are sure."
            )
        return (
            f"The player is interested in {item.name}, {item.title}. "
            f"Describe {item.name} using this detail: {item.description} "
            "Keep it to two vivid sentences. Then ask if this god speaks to them."
        )
    return None


class CardTapHandler:
    """Listens for card tap data channel messages and triggers agent replies."""

    def __init__(self, room: rtc.Room, session: AgentSession, userdata: SessionData) -> None:
        self._room = room
        self._session = session
        self._userdata = userdata
        self._last_hint_time: float = 0.0

    def start(self) -> None:
        self._room.on("data_received", self._on_data_received)

    def stop(self) -> None:
        self._room.off("data_received", self._on_data_received)

    def _on_data_received(self, data: rtc.DataPacket) -> None:
        if data.topic != PLAYER_HINTS_TOPIC:
            return

        now = time.time()
        if now - self._last_hint_time < HINT_COOLDOWN_S:
            logger.debug("Card tap hint ignored (cooldown)")
            return

        if not self._userdata.in_creation:
            return

        try:
            payload = json.loads(data.data)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Invalid card tap payload")
            return

        if payload.get("type") != E.CREATION_CARD_TAP:
            return

        card_id = payload.get("card_id", "")
        category = payload.get("category", "")

        instruction = build_hint_instruction(card_id, category)
        if instruction is None:
            logger.warning("Unknown card tap: %s/%s", category, card_id)
            return

        self._last_hint_time = now
        logger.info("Card tap hint: %s/%s", category, card_id)

        _task = asyncio.create_task(self._session.generate_reply(instructions=instruction))  # noqa: RUF006
