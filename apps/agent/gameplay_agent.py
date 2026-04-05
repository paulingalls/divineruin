"""GameplayAgent — shared base for CityAgent, WildernessAgent, DungeonAgent.

Owns BackgroundProcess lifecycle, session init/end events, hot context
injection, affect analysis forwarding, and delayed session close.
"""

import asyncio
import logging
import time
from typing import Any

from livekit import agents

import db
import event_types as E
from background_process import BackgroundProcess
from base_agent import BaseGameAgent
from combat_resolution import hp_threshold_status
from game_events import publish_game_event
from prompts import build_system_prompt, format_affect_context
from region_types import REGION_CITY, REGION_DUNGEON, REGION_WILDERNESS
from session_data import SessionData
from session_summary import generate_session_summary

logger = logging.getLogger("divineruin.gameplay")


class GameplayAgent(BaseGameAgent):
    """Base for gameplay-type agents (city, wilderness, dungeon).

    Subclasses set ``_agent_type`` and provide their own tool list.
    Everything else — BackgroundProcess, session events, hot context,
    delayed close — is shared.
    """

    _agent_type: str = REGION_CITY  # Override in subclasses

    def __init__(
        self,
        initial_location: str = "accord_guild_hall",
        companion: Any = None,
        chat_ctx: Any = None,
        *,
        tools: list | None = None,
    ) -> None:
        super().__init__(
            instructions=build_system_prompt(initial_location, companion, region_type=self._agent_type),
            tools=tools or [],
            chat_ctx=chat_ctx,
        )
        self._initial_location = initial_location
        self._background: BackgroundProcess | None = None
        self._session_start_time: float = time.time()
        self._close_scheduled: bool = False

    async def _publish_session_init(self, sd: SessionData) -> None:
        try:
            payload = await db.get_session_init_payload(sd.player_id)
            await publish_game_event(sd.room, E.SESSION_INIT, payload, sd.event_bus)
        except Exception:
            logger.exception("Failed to publish session_init")

    async def on_enter(self) -> None:
        await super().on_enter()
        logger.info("%sAgent entered session", self._agent_type.capitalize())
        self._session_start_time = time.time()
        sd: SessionData = self.session.userdata

        self._background = BackgroundProcess(
            agent=self,
            session=self.session,
            session_data=sd,
        )
        self._background.start()
        self._fire_and_forget(self._publish_session_init(sd))

    async def on_exit(self) -> None:
        logger.info("%sAgent exiting session", self._agent_type.capitalize())
        sd: SessionData = self.session.userdata

        transcript_path = self._transcript.log_path if self._transcript else None
        summary_payload = await generate_session_summary(sd, transcript_path, self._session_start_time)

        results = await asyncio.gather(
            publish_game_event(sd.room, E.SESSION_END, summary_payload, sd.event_bus),
            db.save_session_summary(sd.player_id, sd.session_id, summary_payload),
            return_exceptions=True,
        )
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                labels = ("publish session_end", "save session summary")
                logger.exception("Failed to %s", labels[i], exc_info=result)

        try:
            if self._background:
                await self._background.stop()
        except Exception:
            logger.exception("Failed to stop background process")

        await super().on_exit()

    async def on_user_turn_completed(
        self, turn_ctx: agents.llm.ChatContext, new_message: agents.llm.ChatMessage
    ) -> None:
        self._turn_timer.start()
        self._turn_timer.mark("user_turn_end")

        sd: SessionData = self.session.userdata
        sd.last_player_speech_time = time.time()

        hot = self._build_hot_context(sd)
        if hot:
            turn_ctx.add_message(role="assistant", content=hot)

        affect = self._affect_analyzer.get_current_vector()
        if affect:
            turn_ctx.add_message(role="assistant", content=format_affect_context(affect))

    async def on_agent_turn_completed(
        self, turn_ctx: agents.llm.ChatContext, new_message: agents.llm.ChatMessage
    ) -> None:
        sd: SessionData = self.session.userdata
        if sd.ending_requested and not self._close_scheduled:
            self._close_scheduled = True
            self._fire_and_forget(self._delayed_close())

    async def _delayed_close(self) -> None:
        await asyncio.sleep(3.0)
        await self.session.aclose()

    def _build_hot_context(self, sd: SessionData) -> str:
        """Build hot context from in-memory SessionData only — zero I/O."""
        parts: list[str] = []

        loc_name = sd.cached_location_name or sd.location_id
        parts.append(f"[Context: {loc_name}, {sd.world_time}]")

        if sd.combat_state is not None:
            cs = sd.combat_state
            combatants = []
            for pid in cs.initiative_order:
                p = cs.get_participant(pid)
                if p is not None:
                    status = hp_threshold_status(p.hp_current, p.hp_max)
                    combatants.append(f"{p.name}({status})")
            parts.append(f"[COMBAT Round {cs.round_number}: {', '.join(combatants)}]")

        if sd.cached_quest_summaries:
            parts.append("[Quests: " + "; ".join(sd.cached_quest_summaries) + "]")

        if sd.recent_events:
            recent = list(sd.recent_events)[-3:]
            parts.append("[Recent: " + "; ".join(recent) + "]")

        if sd.cached_npc_names:
            parts.append("[NPCs nearby: " + ", ".join(sd.cached_npc_names) + "]")

        return " ".join(parts)


def create_gameplay_agent(
    region_type: str,
    location_id: str,
    companion: Any = None,
    chat_ctx: Any = None,
) -> "GameplayAgent":
    """Factory: instantiate the correct gameplay agent for a region_type."""
    from city_agent import CityAgent
    from dungeon_agent import DungeonAgent
    from wilderness_agent import WildernessAgent

    agents = {
        REGION_CITY: CityAgent,
        REGION_WILDERNESS: WildernessAgent,
        REGION_DUNGEON: DungeonAgent,
    }
    cls = agents.get(region_type, CityAgent)
    return cls(initial_location=location_id, companion=companion, chat_ctx=chat_ctx)
