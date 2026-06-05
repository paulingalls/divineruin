"""ExplorationAgent — the single region-agnostic gameplay agent.

M7 collapses CityAgent/WildernessAgent/DungeonAgent into one agent. Region is a
per-instance attribute (``region_type``), not a class — the location's Stage,
not the agent class, carries the region. One unified tool list (the former city
superset) serves city, wilderness, and dungeon alike.

Owns the BackgroundProcess lifecycle, session init/end events, hot context
injection, affect analysis forwarding, the L5 specialization tap listener, and
delayed session close.
"""

import asyncio
import logging
import time
from typing import Any

from livekit import agents

import db_mutations
import db_queries
import event_types as E
from background_process import BackgroundProcess
from base_agent import BaseGameAgent
from card_tap_handler import SpecializationTapHandler
from check_tools import check
from choice_tools import select
from combat_resolution import hp_threshold_status
from environment_tools import play_sound, set_music_state
from game_events import publish_game_event
from inventory_tools import transact
from mode_tools import enter_mode
from movement_tools import move_player
from progression_tools import award_divine_favor, award_xp
from query_tools import query_info
from quest_tools import update_quest
from region_types import REGION_CITY
from scene_tools import enter_location
from session_data import SessionData
from session_summary import generate_session_summary
from session_tools import end_session, record_story_moment, update_npc_disposition
from system_prompts import build_system_prompt
from warm_prompts import format_affect_context

logger = logging.getLogger("divineruin.exploration")

# The unified verb vocabulary for all exploration (city/wilderness/dungeon). This is
# the former CITY_TOOLS — city's tool list was already a strict superset of the
# wilderness and dungeon lists, so one list serves every region. With a single agent
# there is no per-region ceiling pressure: 15 verbs leave 5 free slots under
# MAX_STRICT_TOOLS (relieves debt e665104c753a). The settlement-flavoured verbs
# (transact, award_divine_favor, update_npc_disposition) are exposed everywhere; the
# warm-layer REGISTER (story-002) carries the when-appropriate guidance per ADR 0007 —
# the Stage gates applicability, not per-agent tool lists.
EXPLORATION_TOOLS = [
    # World query
    enter_location,
    query_info,
    check,
    # Mechanics
    play_sound,
    set_music_state,
    # Mutation
    move_player,
    transact,
    update_quest,
    award_xp,
    award_divine_favor,
    update_npc_disposition,
    record_story_moment,
    end_session,
    # Choice resolution: the L5 specialization fork (surfaced by award_xp on level-up)
    # resolves via the generic select verb (concern 3c02318dfa99).
    select,
    # Mode handoffs (combat / dispatch / blacksmith) fold into the single enter_mode
    # verb (M5, ADR 0007); their focused toolsets live on the respective mode agents.
    enter_mode,
]


class ExplorationAgent(BaseGameAgent):
    """The single gameplay agent for city, wilderness, and dungeon locations.

    ``region_type`` is set per instance and stored as ``_agent_type`` so the
    mode-agent handoffs (combat/dispatch/blacksmith) can remember which region to
    return to via ``getattr(agent, "_agent_type", ...)``.
    """

    def __init__(
        self,
        initial_location: str = "accord_guild_hall",
        companion: Any = None,
        chat_ctx: Any = None,
        *,
        region_type: str = REGION_CITY,
        tools: list | None = None,
    ) -> None:
        self._agent_type = region_type
        super().__init__(
            instructions=build_system_prompt(initial_location, companion),
            tools=tools or EXPLORATION_TOOLS,
            chat_ctx=chat_ctx,
        )
        self._initial_location = initial_location
        self._background: BackgroundProcess | None = None
        self._spec_tap: SpecializationTapHandler | None = None
        self._session_start_time: float = time.time()
        self._close_scheduled: bool = False

    async def _publish_session_init(self, sd: SessionData) -> None:
        try:
            payload = await db_queries.get_session_init_payload(sd.player_id)
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

        # Consume L5 specialization taps from the HUD: a tap drives the DM to resolve
        # the fork via the select verb (story-008, concern c6b7b18f2d8f).
        assert sd.room is not None  # room is set before agent enters
        self._spec_tap = SpecializationTapHandler(room=sd.room, session=self.session, userdata=sd)
        self._spec_tap.start()

    async def on_exit(self) -> None:
        logger.info("%sAgent exiting session", self._agent_type.capitalize())
        if self._spec_tap:
            self._spec_tap.stop()
        sd: SessionData = self.session.userdata

        transcript_path = self._transcript.log_path if self._transcript else None
        summary_payload = await generate_session_summary(sd, transcript_path, self._session_start_time)

        results = await asyncio.gather(
            publish_game_event(sd.room, E.SESSION_END, summary_payload, sd.event_bus),
            db_mutations.save_session_summary(sd.player_id, sd.session_id, summary_payload),
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

        # M6 same-turn reveal: surface elements discovered this turn (appended by the
        # E.HIDDEN_REVEALED handler), then clear so the reveal doesn't echo next turn. The
        # warm rebuild absorbs them into the affordances on its next pass.
        if sd.recently_revealed_element_ids:
            parts.append("[Revealed: " + ", ".join(sd.recently_revealed_element_ids) + "]")
            sd.recently_revealed_element_ids.clear()

        return " ".join(parts)
