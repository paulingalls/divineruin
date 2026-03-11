"""Interruptible prologue narration for new player sessions."""

import asyncio
import logging

from livekit import rtc
from livekit.agents import AgentSession
from livekit.agents.voice.events import UserStateChangedEvent

import event_types as E
from game_events import publish_game_event

logger = logging.getLogger("divineruin.prologue")

PROLOGUE_DURATION_S = 70
PROLOGUE_URL = "/api/audio/prologue.mp3"
MAX_PARTICIPANT_WAIT_S = 15.0


async def _wait_for_participant(room: rtc.Room) -> None:
    """Wait until at least one remote participant is in the room."""
    if room.remote_participants:
        return

    joined = asyncio.Event()

    def _on_join(_participant: rtc.RemoteParticipant) -> None:
        joined.set()

    room.on("participant_connected", _on_join)
    try:
        await asyncio.wait_for(joined.wait(), timeout=MAX_PARTICIPANT_WAIT_S)
    except TimeoutError:
        logger.warning("No participant joined after %.1fs — sending prologue anyway", MAX_PARTICIPANT_WAIT_S)
    finally:
        room.off("participant_connected", _on_join)


async def play_prologue(session: AgentSession, room: rtc.Room) -> bool:
    """Play the prologue narration, interruptible by player speech.

    Returns True if the player interrupted (spoke during playback).
    """
    await _wait_for_participant(room)
    await publish_game_event(room, E.PLAY_NARRATION, {"url": PROLOGUE_URL})

    player_spoke = asyncio.Event()

    def _on_user_state(ev: UserStateChangedEvent) -> None:
        if ev.new_state == "speaking":
            player_spoke.set()

    session.on("user_state_changed", _on_user_state)

    sleep_task = asyncio.create_task(asyncio.sleep(PROLOGUE_DURATION_S))
    speak_task = asyncio.create_task(player_spoke.wait())

    try:
        _done, pending = await asyncio.wait(
            {sleep_task, speak_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    finally:
        session.off("user_state_changed", _on_user_state)

    interrupted = player_spoke.is_set()
    if interrupted:
        logger.info("Player spoke during prologue — skipping remaining narration")
        await publish_game_event(room, E.STOP_NARRATION, {})

    return interrupted
