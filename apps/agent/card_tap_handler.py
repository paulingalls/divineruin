"""Handlers for client data-channel hints (topic "player_hints").

CardTapHandler narrates a tapped creation card during character creation.
SpecializationTapHandler resolves a tapped L5 specialization during gameplay by
driving the DM to call the select verb with the chosen id. Both share
_PlayerHintsListener — the data-channel subscription, topic filter, cooldown, and
JSON parse, and the LiveKit-verified sender — and implement _handle for their own
event type.
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
from session_data import SessionData, SpecializationTap
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

    Deliberately carries NO player identity (decision 5829eecd76eb). WHOSE fork this is
    travels out-of-band on SessionData.pending_specialization_tap, because in the tie the
    identity exists to break, a model that mis-copied an id into the argument would pass
    every one of select's checks and permanently write one member's choice onto another's.
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

        # DataPacket.participant.identity IS the player_id — participant_lifecycle compares
        # it directly — so the LiveKit-verified sender needs no mapping to be usable. Empty
        # when the packet carries no participant; subclasses that need it validate it.
        sender = data.participant.identity if data.participant else ""
        if self._handle(payload, sender):
            self._last_hint_time = now

    def _handle(self, payload: dict, sender: str) -> bool:
        """Dispatch a parsed payload; return True iff a reply was triggered.

        ``sender`` is the LiveKit-verified identity of the participant that published the
        packet, or "" if the packet had none.
        """
        raise NotImplementedError


class CardTapHandler(_PlayerHintsListener):
    """Narrates a tapped creation card during character creation."""

    def _handle(self, payload: dict, sender: str) -> bool:
        # ``sender`` is unused here by construction: character creation is single-player —
        # the party is the one PC being created, so there is nobody else a tap could belong
        # to. Only the gameplay L5 fork (below) has an owner worth recording.
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

    Rewards are party-wide (M28 story-001), so the tapper is not necessarily the primary.
    The tap records its verified sender on SessionData for select to consume, which is what
    keeps a teammate's choice off the primary's write-once row (M28 story-008).
    """

    def _handle(self, payload: dict, sender: str) -> bool:
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

        # Record the verified sender as a one-shot ticket for select to consume, so a
        # non-primary member's fork resolves onto THEIR row (M28 story-008). Its OWN try:
        # a sender we cannot validate must cost only the ticket, never the tap — with no
        # ticket select falls back to the sole-claimant party scan, which is exactly right
        # for the solo session an identity-less tap comes from. Sharing the guard above
        # would return False and swallow the tap entirely.
        try:
            _validate_id(sender, "sender")
            ticket: SpecializationTap | None = SpecializationTap(sender, milestone_id, specialization_id)
        except ToolError:
            logger.warning("Specialization tap: unusable sender %r; select will fall back to the party scan", sender)
            ticket = None
        # Always replace, never leave an earlier tap's ticket standing: this tap is the most
        # recent statement of who is choosing, and a stale one could resolve THIS tap onto
        # the earlier tapper's write-once row. Set before generate_reply — select consumes
        # it during the reply this triggers.
        self._userdata.pending_specialization_tap = ticket

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
