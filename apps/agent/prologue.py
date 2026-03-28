"""Prologue narration for new player sessions.

Streams the prologue MP3 through the agent's WebRTC audio track so that
iOS acoustic echo cancellation prevents the VAD from hearing the narration
through the microphone.  The player can interrupt by speaking.
"""

import asyncio
import logging
import os

from livekit import rtc
from livekit.agents import AgentSession
from livekit.agents.utils.audio import audio_frames_from_file

logger = logging.getLogger("divineruin.prologue")

AUDIO_DIR = os.environ.get(
    "ASYNC_AUDIO_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "assets", "audio"),
)
PROLOGUE_PATH = os.path.join(AUDIO_DIR, "prologue.mp3")
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
        logger.warning("No participant joined after %.1fs — starting prologue anyway", MAX_PARTICIPANT_WAIT_S)
    finally:
        room.off("participant_connected", _on_join)


async def play_prologue(session: AgentSession, room: rtc.Room) -> bool:
    """Play prologue narration through the agent's voice track.

    Returns True if the player interrupted (spoke during playback).
    """
    await _wait_for_participant(room)

    if not os.path.isfile(PROLOGUE_PATH):
        logger.error("Prologue audio not found at %s — skipping", PROLOGUE_PATH)
        return False

    logger.info("Starting prologue via agent audio track: %s", PROLOGUE_PATH)
    frames = audio_frames_from_file(PROLOGUE_PATH, sample_rate=24000, num_channels=1)

    handle = session.say(
        text="",
        audio=frames,
        allow_interruptions=True,
        add_to_chat_ctx=False,
    )

    await handle.wait_for_playout()

    interrupted = handle.interrupted
    if interrupted:
        logger.info("Player interrupted prologue")
    else:
        logger.info("Prologue finished")

    return interrupted
