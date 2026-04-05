"""Audio/environment tools for the DM agent."""

import json
import logging
from typing import Literal

from livekit.agents.llm import function_tool
from livekit.agents.voice import RunContext

import event_types as E
from game_events import publish_game_event
from session_data import SessionData

logger = logging.getLogger("divineruin.tools")

SoundName = Literal[
    "sword_clash",
    "tavern",
    "spell_cast",
    "arrow_loose",
    "hit_taken",
    "shield_block",
    "potion_use",
    "door_creak",
    "discovery_chime",
    "notification",
    "god_whisper_stinger",
]


@function_tool()
async def play_sound(
    context: RunContext[SessionData],
    sound_name: SoundName,
) -> str:
    """Play a sound effect on the client."""
    logger.info("play_sound called: sound_name=%s", sound_name)
    session: SessionData = context.userdata

    await publish_game_event(
        session.room,
        E.PLAY_SOUND,
        {
            "sound_name": sound_name,
        },
        event_bus=session.event_bus,
    )

    session.record_event(f"Sound: {sound_name}")

    return json.dumps({"status": "playing", "sound_name": sound_name})


MusicStateName = Literal["wonder", "sorrow", "tension", "silence"]
_VALID_MUSIC_STATES: set[str] = {"wonder", "sorrow", "tension", "silence"}


@function_tool()
async def set_music_state(
    context: RunContext[SessionData],
    music_state: MusicStateName,
) -> str:
    """Set the background music mood. Use sparingly for specific emotional
    moments the player should feel. Combat and exploration music are handled
    automatically — do not set those here."""
    logger.info("set_music_state called: music_state=%s", music_state)

    # Runtime safety net — Literal type handles SDK validation, but _func
    # calls (tests, internal use) bypass that check.
    if music_state not in _VALID_MUSIC_STATES:
        return json.dumps(
            {"error": f"Invalid music state: {music_state}. Valid: {', '.join(sorted(_VALID_MUSIC_STATES))}"}
        )

    session: SessionData = context.userdata

    await publish_game_event(
        session.room,
        E.SET_MUSIC_STATE,
        {"music_state": music_state},
        event_bus=session.event_bus,
    )

    session.record_event(f"Music: {music_state}")

    return json.dumps({"status": "set", "music_state": music_state})
