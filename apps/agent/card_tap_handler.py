"""Handlers for client data-channel hints (topic "player_hints").

CardTapHandler narrates a tapped creation card during character creation.
SpecializationTapHandler resolves a tapped L5 specialization during gameplay by
driving the DM to call the select verb with the chosen id. Both share
_PlayerHintsListener — the data-channel subscription, topic filter, cooldown, and
JSON parse — and implement _handle for their own event type.
"""

from __future__ import annotations

import json
import logging
import time

from livekit import rtc
from livekit.agents import AgentSession
from livekit.agents.llm import ToolError

import event_types as E
from creation_classes import CLASSES
from creation_deities import DEITIES
from creation_races import RACES
from session_data import SessionData
from tool_support import _validate_id

logger = logging.getLogger("divineruin.card_tap")

HINT_COOLDOWN_S = 2.0
PLAYER_HINTS_TOPIC = "player_hints"


def build_hint_instruction(card_id: str, category: str) -> str | None:
    """Build an instruction for the agent to narrate a tapped card.

    Returns None if the card_id/category is invalid.
    Uses the full ``description`` field (ear-first narration text).
    """
    no_tools = "Do NOT call push_creation_cards or any other tool — just narrate."

    if category == "race" and card_id in RACES:
        item = RACES[card_id]
        return (
            f"The player tapped the {item.name} card. "
            f"Describe what it feels like to be a {item.name} using this detail: {item.description} "
            f"Keep it to two vivid sentences. Then ask if this is what they feel. {no_tools}"
        )
    elif category == "class" and card_id in CLASSES:
        item = CLASSES[card_id]
        return (
            f"The player tapped the {item.name} card ({item.category}). "
            f"Describe the {item.name} using this detail: {item.description} "
            f"Keep it to two vivid sentences. Then ask if this is their calling. {no_tools}"
        )
    elif category == "deity" and card_id in DEITIES:
        item = DEITIES[card_id]
        if card_id == "none":
            return (
                "The player is considering walking without a patron. "
                f"Describe: {item.description} "
                f"Keep it to two sentences. Ask if they are sure. {no_tools}"
            )
        return (
            f"The player tapped the {item.name} card, {item.title}. "
            f"Describe {item.name} using this detail: {item.description} "
            f"Keep it to two vivid sentences. Then ask if this god speaks to them. {no_tools}"
        )
    return None


def build_specialization_instruction(milestone_id: str, specialization_id: str) -> str:
    """Instruction telling the DM to lock in the tapped L5 specialization.

    The DM calls the select verb with the pending choice_id (the milestone id) and the
    chosen option — select is the gatekeeper that validates against the fork options and
    persists immutably — then voices it.
    """
    return (
        f"The player tapped to choose the {specialization_id} specialization. "
        f'Call select with choice_id="{milestone_id}" and option="{specialization_id}" to '
        "lock it in, then narrate embracing this path in one or two vivid sentences. "
        "This choice is permanent."
    )


class _PlayerHintsListener:
    """Base: listen on the player_hints data channel; parse + cooldown; dispatch to _handle.

    ``_last_hint_time`` advances ONLY when ``_handle`` dispatches a reply (returns
    True), so an ignored payload never starts the cooldown and blocks a following
    valid hint.
    """

    def __init__(self, room: rtc.Room, session: AgentSession, userdata: SessionData) -> None:
        self._room = room
        self._session = session
        self._userdata = userdata
        self._last_hint_time: float = 0.0

    def start(self) -> None:
        logger.info("%s started, listening for data_received events", type(self).__name__)
        self._room.on("data_received", self._on_data_received)

    def stop(self) -> None:
        self._room.off("data_received", self._on_data_received)

    def _on_data_received(self, data: rtc.DataPacket) -> None:
        if data.topic != PLAYER_HINTS_TOPIC:
            return

        now = time.time()
        if now - self._last_hint_time < HINT_COOLDOWN_S:
            logger.debug("player_hints tap ignored (cooldown)")
            return

        try:
            payload = json.loads(data.data)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Invalid player_hints payload")
            return

        if self._handle(payload):
            self._last_hint_time = now

    def _handle(self, payload: dict) -> bool:
        """Dispatch a parsed payload; return True iff a reply was triggered."""
        raise NotImplementedError


class CardTapHandler(_PlayerHintsListener):
    """Narrates a tapped creation card during character creation."""

    def _handle(self, payload: dict) -> bool:
        if not self._userdata.in_creation:
            return False
        if payload.get("type") != E.CREATION_CARD_TAP:
            return False

        card_id = payload.get("card_id", "")
        category = payload.get("category", "")
        instruction = build_hint_instruction(card_id, category)
        if instruction is None:
            logger.warning("Unknown card tap: %s/%s", category, card_id)
            return False

        logger.info("Card tap hint: %s/%s", category, card_id)
        self._session.generate_reply(
            user_input=f"[The player tapped the {card_id} card]",
            instructions=instruction,
            tool_choice="none",
        )
        return True


class SpecializationTapHandler(_PlayerHintsListener):
    """Resolves a tapped L5 specialization during gameplay via the DM (story-005).

    On a SPECIALIZATION_CHOICE_TAP, drives the DM (generate_reply) to call the select
    verb with the pending choice_id (the milestone_id the client echoes back from the
    SPECIALIZATION_CHOICE event) and the chosen option — instruction-driven so the DM
    voices the confirmation (audio-first), with select the validation/persistence
    gatekeeper. Active wherever leveling happens — the exploration agents (story-008)
    and the dispatch/training context (story-004) — started via start_specialization_tap.

    Shares the base HINT_COOLDOWN_S debounce intentionally: the L5 choice is a one-shot
    permanent pick, so the 2s window only suppresses accidental double-taps.
    """

    def _handle(self, payload: dict) -> bool:
        if payload.get("type") != E.SPECIALIZATION_CHOICE_TAP:
            return False
        milestone_id = payload.get("milestone_id", "")
        specialization_id = payload.get("specialization_id", "")
        # Validate the untrusted ids with the canonical guard before interpolating them
        # into the LLM instruction (debt 9a6b6e5dc762); select re-validates downstream.
        try:
            _validate_id(milestone_id, "milestone_id")
            _validate_id(specialization_id, "specialization_id")
        except ToolError:
            logger.warning("Specialization tap dropped: invalid ids (%r / %r)", milestone_id, specialization_id)
            return False

        logger.info("Specialization tap: %s -> %s", milestone_id, specialization_id)
        self._session.generate_reply(
            user_input=f"[The player chose the {specialization_id} specialization]",
            instructions=build_specialization_instruction(milestone_id, specialization_id),
        )
        return True


def start_specialization_tap(room: rtc.Room, session: AgentSession, userdata: SessionData) -> SpecializationTapHandler:
    """Construct and start the L5 specialization-tap consumer, returning the handler.

    Shared by every agent context where leveling happens — exploration (story-008) and
    dispatch/training (story-004) — so the tap construct+start lives in one place. The
    caller stores the handler and stops it in on_exit (``handler.stop()``).
    """
    handler = SpecializationTapHandler(room=room, session=session, userdata=userdata)
    handler.start()
    return handler
