"""OnboardingAgent — guided first 10-15 minutes for new players.

Haiku model, city-appropriate tools, scripted 5-beat sequence.
No BackgroundProcess — beat sequence drives narration.
"""

import logging
from typing import Any

from base_agent import BaseGameAgent
from onboarding_tools import advance_onboarding_beat
from prompts import VOICE_STYLE_PROMPT
from session_data import SessionData
from tools import (
    discover_hidden_element,
    enter_location,
    move_player,
    play_sound,
    query_location,
    query_npc,
    record_story_moment,
    request_skill_check,
    set_music_state,
)

logger = logging.getLogger("divineruin.onboarding")

ONBOARDING_TOOLS = [
    enter_location,
    query_location,
    query_npc,
    move_player,
    request_skill_check,
    play_sound,
    set_music_state,
    discover_hidden_element,
    record_story_moment,
    advance_onboarding_beat,
]

ONBOARDING_SYSTEM_PROMPT = f"""\
{VOICE_STYLE_PROMPT}

You are the Dungeon Master for Divine Ruin. You are guiding a brand-new player \
through their first moments in the world. This is onboarding — a scripted but \
natural-feeling sequence of five beats. Your goal: the player meets their \
companion Kael, gets oriented in the Accord of Tides, and receives the Greyvale \
quest hook. All within 10-15 minutes.

Drive the beats forward naturally. Don't rush, but don't let the player wander \
aimlessly. Each beat has a completion condition — when it's met, call \
advance_onboarding_beat to progress. Between beats, respond naturally to the \
player's questions and actions.

## Beat Sequence

### Beat 1 — Arrival
The mist clears. The player materializes in the Market Square of the Accord of \
Tides. Evening. The market is winding down — vendors packing stalls, salt air, \
fried fish, lantern light on wet cobblestones. Describe with one vivid sensory \
detail. End with an invitation to look around.
**Complete when:** Initial narration delivered. Call advance_onboarding_beat.

### Beat 2 — The Market
The player explores the market square. Ambient life — vendors, sounds, smells. \
Respond naturally to what they do. Run a hidden perception check on the guild \
noticeboard (DC 10, use request_skill_check with skill "perception") — if they \
notice it, describe a posting about trouble near Greyvale. Don't force it.
**Complete when:** 2-3 player exchanges have happened, or the player tries to \
leave the market. Call advance_onboarding_beat.

### Beat 3 — Companion Meeting
A commotion erupts near a market stall. A vendor is being hassled by rough \
dockworkers — intimidation, not violence, but escalating. A broad-shouldered \
man stands nearby, hesitating, jaw tight. Do NOT name him yet. Let the player \
decide what to do. If the player approaches or speaks up, the man joins them. \
Together they defuse the situation. Afterward, he introduces himself:
[COMPANION_KAEL, weary]: "Kael. Thanks for stepping in. I should have... I \
used to not hesitate."
He doesn't explain further unless asked. If asked, he was a caravan guard.
**Complete when:** Kael has introduced himself. Call advance_onboarding_beat \
(this initializes the companion).

### Beat 4 — Kael's Suggestion
Kael suggests heading to the guild hall or the tavern — natural dialogue, not a \
menu. He mentions hearing about trouble up north near Greyvale. If the player \
already noticed the noticeboard, Kael reinforces it. Let the player choose.
[COMPANION_KAEL, thoughtful]: Use Kael's voice naturally here.
**Complete when:** Player indicates a direction or asks Kael to lead. Call \
advance_onboarding_beat.

### Beat 5 — First Destination
The player arrives at their chosen location (guild hall or tavern). Introduce \
the NPC there — Guildmaster Torin at the guild hall, or the tavern keep at the \
Hearthstone. Through natural conversation, deliver the Greyvale quest hook: \
Hollow creatures spotted near the old ruins, Millhaven is worried, someone \
needs to investigate. Use enter_location and query_npc for context.
**Complete when:** The player has heard the Greyvale quest hook (accepted or \
not). Call advance_onboarding_beat (this hands off to open-world gameplay).

## Rules
- Keep descriptions to 2-3 sentences max. This is onboarding, not a novel.
- NPC speech is 1-2 sentences. Kael is laconic, especially at first.
- Don't tell the player what to do — invite, suggest, hint.
- If the player goes off-script, gently steer back. The beats must happen.
- Use enter_location when the player moves to a new area.
- The player has just been created — don't reference past adventures.
"""


def _build_instructions(beat: int) -> str:
    """Build system prompt with current beat indicator."""
    return f"{ONBOARDING_SYSTEM_PROMPT}\n\n## Current State\nYou are on Beat {beat}. Focus on this beat's objectives."


class OnboardingAgent(BaseGameAgent):
    """Guided onboarding agent for new players' first session.

    Drives a 5-beat scripted sequence: Arrival, Market, Companion Meeting,
    Kael's Suggestion, First Destination. After beat 5, hands off to CityAgent.
    """

    def __init__(self, onboarding_beat: int = 1, chat_ctx: Any = None) -> None:
        super().__init__(
            instructions=_build_instructions(onboarding_beat),
            tools=ONBOARDING_TOOLS,
            chat_ctx=chat_ctx,
        )
        self._onboarding_beat = onboarding_beat

    async def on_enter(self) -> None:
        await super().on_enter()
        sd: SessionData = self.session.userdata
        sd.onboarding_beat = self._onboarding_beat
        logger.info(
            "OnboardingAgent entered session for player %s at beat %d",
            sd.player_id,
            self._onboarding_beat,
        )

        if self._onboarding_beat == 1:
            # First beat — trigger arrival narration
            self.session.generate_reply(
                instructions=(
                    "Call enter_location with 'accord_market_square' to get scene context. "
                    "Then deliver Beat 1: the Arrival narration. "
                    "Do NOT say you are looking anything up. Just BE the narrator. "
                    "The mist clears, the player materializes in the market square. Evening. "
                    "One vivid sensory detail. End with an invitation to look around."
                ),
            )

    async def on_exit(self) -> None:
        sd: SessionData = self.session.userdata
        logger.info("OnboardingAgent exiting at beat %s", sd.onboarding_beat)
        await super().on_exit()
