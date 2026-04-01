"""OnboardingBackgroundProcess — lightweight stall detection for beats 4-5.

Timer-based polling loop that delivers predefined Kael nudges when the player
stalls during onboarding beats 4-5. No warm layer, no event bus, no combat.
"""

import asyncio
import logging
import time

from livekit.agents import AgentSession

from session_data import SessionData

logger = logging.getLogger("divineruin.onboarding_background")

NUDGE_DELAY_SECONDS = 30
POLL_INTERVAL_SECONDS = 5

ONBOARDING_NUDGES: dict[int, list[str]] = {
    4: [
        (
            "Kael shifts his weight and glances down the street. "
            "Have him casually suggest heading to the guild hall or the tavern — "
            "he's heard both are worth checking out. One sentence. "
            "Use [COMPANION_KAEL, thoughtful] tag."
        ),
        (
            "Kael looks at the player and offers to lead the way. "
            "Have him ask if they want to head out together. One sentence. "
            "Use [COMPANION_KAEL, steady] tag."
        ),
        (
            "Kael starts walking slowly toward the guild hall district. "
            "Have him say they should get moving before it gets too late. "
            "One sentence, slightly urgent. Use [COMPANION_KAEL, focused] tag."
        ),
    ],
    5: [
        (
            "Kael nods toward the NPC in the room. "
            "Have him suggest the player introduce themselves and ask about "
            "the situation near Greyvale. One sentence. "
            "Use [COMPANION_KAEL, encouraging] tag."
        ),
        (
            "Kael leans in and quietly reminds the player about the trouble "
            "near Greyvale — they should ask about it here. One sentence. "
            "Use [COMPANION_KAEL, focused] tag."
        ),
    ],
}


class OnboardingBackgroundProcess:
    """Lightweight background process for onboarding beats 4-5.

    Polls for player silence and delivers predefined Kael nudges
    to guide new players through their first navigation experience.
    """

    def __init__(self, session: AgentSession, session_data: SessionData) -> None:
        self._session = session
        self._sd = session_data
        self._hint_index = 0
        self._last_hint_time = 0.0
        self._last_active_beat: int | None = None
        self._stop = False
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop = True
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        while not self._stop:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            if self._stop:
                break
            await self._check_nudge()

    async def _check_nudge(self) -> None:
        beat = self._sd.onboarding_beat
        if beat is None or beat < 4:
            return

        if beat != self._last_active_beat:
            self._hint_index = 0
            self._last_hint_time = 0.0
            self._last_active_beat = beat

        nudges = ONBOARDING_NUDGES.get(beat)
        if not nudges or self._hint_index >= len(nudges):
            return

        if self._sd.last_player_speech_time <= 0:
            return

        baseline = max(self._sd.last_player_speech_time, self._sd.last_agent_speech_end)
        if self._last_hint_time > 0:
            baseline = max(baseline, self._last_hint_time)

        now = time.time()
        if now - baseline < NUDGE_DELAY_SECONDS:
            return

        instruction = nudges[self._hint_index]
        logger.info(
            "Delivering onboarding nudge %d for beat %d to player %s",
            self._hint_index,
            beat,
            self._sd.player_id,
        )
        await self._session.generate_reply(instructions=instruction)
        self._hint_index += 1
        self._last_hint_time = now

        if self._sd.companion:
            self._sd.companion.last_speech_time = now
