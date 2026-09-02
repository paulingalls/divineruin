"""OnboardingBackgroundProcess — lightweight stall detection for beats 4-5."""

import asyncio
import logging
import time

from livekit.agents import AgentSession

from session_data import SessionData
from system_prompts import build_companion_cue

logger = logging.getLogger("divineruin.onboarding_background")

NUDGE_DELAY_SECONDS = 30
POLL_INTERVAL_SECONDS = 5

ONBOARDING_NUDGES: dict[int, list[tuple[str, str]]] = {
    4: [
        (
            "glances down the street and casually suggests heading to the guild hall or tavern, both worth exploring.",
            "thoughtful",
        ),
        (
            "offers to lead the way and asks whether the player wants to head out together.",
            "steady",
        ),
        (
            "starts toward the guild hall district and urges the player to get moving before it gets late.",
            "focused",
        ),
    ],
    5: [
        (
            "indicates the nearby person and suggests an introduction and a question about Greyvale.",
            "encouraging",
        ),
        (
            "quietly reminds the player to ask about the trouble near Greyvale.",
            "focused",
        ),
    ],
}


class OnboardingBackgroundProcess:
    """Poll for player silence and guide beats 4-5 with companion nudges."""

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

        companion = self._sd.companion
        if companion is None:
            logger.error(
                "Cannot deliver onboarding nudge for player %s at beat %d without a companion",
                self._sd.player_id,
                beat,
            )
            return

        staging, emotion = nudges[self._hint_index]
        instruction = build_companion_cue(companion, staging, emotion)
        logger.info(
            "Delivering onboarding nudge %d for beat %d to player %s",
            self._hint_index,
            beat,
            self._sd.player_id,
        )
        await self._session.generate_reply(instructions=instruction)
        self._hint_index += 1
        self._last_hint_time = now

        companion.last_speech_time = now
