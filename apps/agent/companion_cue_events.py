"""Publish companion cues for the client HUD."""

import logging
from typing import TYPE_CHECKING

from livekit.rtc.participant import PublishDataError

import event_types as E
from companion_profiles import get_companion_profile
from game_events import publish_game_event

if TYPE_CHECKING:
    from session_data import CompanionState, SessionData

logger = logging.getLogger("divineruin.companion_cue_events")


async def publish_companion_cue(sd: "SessionData", companion: "CompanionState") -> None:
    profile = get_companion_profile(companion.id)
    try:
        await publish_game_event(sd.room, E.COMPANION_CUE, {"voice_id": profile.voice_id})
    except PublishDataError:
        logger.error("Failed to publish companion cue", exc_info=True)
