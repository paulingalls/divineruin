"""ExplorationAgent — the single region-agnostic gameplay agent.

M7 collapses CityAgent/WildernessAgent/DungeonAgent into one agent. Region is a
per-instance attribute (``region_type``), not a class — the location's Stage,
not the agent class, carries the region. One unified tool list (the former city
superset) serves city, wilderness, and dungeon alike.

Starts the SESSION's BackgroundProcess (once — it outlives every mode handoff and is
stopped by the session's close, not by this agent's exit), the session init event, hot context
injection, affect analysis forwarding, the L5 specialization tap listener, and
delayed session close. The session END is not here: see ``session_end.py``.
"""

import asyncio
import logging
import time
from functools import partial
from typing import Any

from livekit import agents

import db_activity_queries
import db_queries
import db_session_queries
import db_training
import event_types as E
from activate_tools import activate
from background_process import BackgroundProcess
from base_agent import BaseGameAgent
from card_tap_handler import SpecializationTapHandler, start_specialization_tap
from check_tools import check
from choice_tools import select
from game_events import publish_game_event
from inventory_tools import transact
from mode_tools import enter_mode
from movement_tools import move_player
from query_tools import query_info
from quest_tools import update_quest
from region_types import REGION_CITY
from reputation_tools import adjust_faction_reputation
from sanitize import sanitize_for_prompt
from scene_tools import enter_location
from session_data import SessionData
from session_tools import end_session, record_story_moment, update_npc_disposition
from system_prompts import build_system_prompt
from task_logging import log_task_failure
from travel_tools import travel
from warm_prompts import format_affect_context, format_combat_hot_line, quest_objective

logger = logging.getLogger("divineruin.exploration")

# The pause between the DM's narrative wrap-up and the actual session close, so the
# player hears the goodbye finish before the recap arrives. Named so a test can shorten
# it without patching `asyncio.sleep`, which is the shared module object — patching it
# there stubs the vendor's timing for everything running in the same block.
CLOSE_DELAY_S = 3.0


# The unified verb vocabulary for all exploration (city/wilderness/dungeon). This is
# the former CITY_TOOLS — city's tool list was already a strict superset of the
# wilderness and dungeon lists, so one list serves every region. With a single agent
# there is no per-region ceiling pressure: 14 verbs leave 6 free slots under
# MAX_STRICT_TOOLS (relieves debt e665104c753a). The settlement-flavoured verbs
# (transact, update_npc_disposition) are exposed everywhere; the
# warm-layer REGISTER (story-002) carries the when-appropriate guidance per ADR 0007 —
# the Stage gates applicability, not per-agent tool lists.
#
# activate (M25 Phase-5 story-003) replaces the item-use deploy_veil_anchor: it is the
# same polymorphic capability verb registered on combat (story-002), routing a Veil
# Anchor item id to _deploy_veil_anchor_impl. Registering it here also makes
# activate_veil_ward's out-of-combat LOCATION-scope raise reachable for the first time —
# previously only combat held a ward-raising tool, so a Cleric/Druid could never raise
# an "until dismissed" location ward outside a fight (debt 67ae0f87df29). Net-zero swap:
# the list stays at net-zero here; M27 story-003 separately tore out play_sound/
# set_music_state (18->16) — audio derives only from deterministic Resolves and the Stage.
# M28 story-003 tore out award_xp/award_divine_favor the same way (16->14): XP and favor are
# granted by the combat-exit and quest-completion Resolves, never by LLM judgement.
EXPLORATION_TOOLS = [
    # World query
    enter_location,
    query_info,
    check,
    # Mutation
    move_player,
    travel,
    transact,
    update_quest,
    update_npc_disposition,
    adjust_faction_reputation,
    record_story_moment,
    end_session,
    # Polymorphic capability activation (M25 Phase-5 story-003): spells, abilities, Veil
    # Anchor deployment, and Veil Ward raise/dismiss all route through one verb.
    activate,
    # Choice resolution: the L5 specialization fork (surfaced by the XP Resolve on level-up)
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
        self._spec_tap: SpecializationTapHandler | None = None
        self._close_scheduled: bool = False
        self._close_task: asyncio.Task | None = None

    async def _publish_session_init(self, sd: SessionData) -> None:
        try:
            payload = await db_session_queries.get_session_init_payload(sd.primary_player_id)
            await publish_game_event(sd.room, E.SESSION_INIT, payload, sd.event_bus)
        except Exception:
            logger.exception("Failed to publish session_init")

    async def _enter(self) -> None:
        await super()._enter()
        logger.info("%sAgent entered session", self._agent_type.capitalize())
        sd: SessionData = self.session.userdata

        # Session-scoped, and started at most once: a handback from combat/dispatch enters a
        # NEW ExplorationAgent instance over the same SessionData, and nothing stops the first
        # loop any more. The bus is a QUEUE, so two loops do not duplicate the stream — they
        # SPLIT it, each seeing half the events and keeping its own quest/scene/warm caches, and
        # both rebuilding on the 30s fallback. That is a doubled DB fan-out over two divergent
        # warm layers racing each other into the same agent.
        if sd.background is None:
            sd.background = BackgroundProcess(session=self.session, session_data=sd)
            sd.background.start()
        self._fire_and_forget(self._publish_session_init(sd))

        # Consume L5 specialization taps from the HUD: a tap drives the DM to resolve
        # the fork via the select verb (story-008, concern c6b7b18f2d8f).
        assert sd.room is not None  # room is set before agent enters
        self._spec_tap = start_specialization_tap(sd.room, self.session, sd)

    async def on_exit(self) -> None:
        """Agent-scoped teardown ONLY — this runs on every mode handoff, not at session end.

        The session summary, the SESSION_END publish and the summary row live in
        ``session_end.run_session_end``, fired from the session's own ``close`` event.
        """
        logger.info("%sAgent exiting session", self._agent_type.capitalize())
        if self._spec_tap:
            self._spec_tap.stop()
        await super().on_exit()

    async def on_user_turn_completed(
        self, turn_ctx: agents.llm.ChatContext, new_message: agents.llm.ChatMessage
    ) -> None:
        self._turn_timer.start()
        self._turn_timer.mark("user_turn_end")

        sd: SessionData = self.session.userdata
        sd.last_player_speech_time = time.time()

        speaker_id = sd.acting_player_id
        player, quests, activities, training = await asyncio.gather(
            db_queries.get_player(speaker_id),
            db_queries.get_active_player_quests(speaker_id),
            db_activity_queries.get_player_activities(speaker_id, status="in_progress"),
            db_training.get_player_active_training_activities(speaker_id),
        )
        if player is None:
            raise RuntimeError(f"Missing speaker player {speaker_id!r}")
        speaker = self._build_speaker_context(speaker_id, player, quests, activities, training)
        turn_ctx.add_message(role="assistant", content=speaker + " " + self._build_hot_context(sd))

        affect = self._affect_analyzer.get_current_vector()
        if affect:
            turn_ctx.add_message(role="assistant", content=format_affect_context(affect))

    async def on_agent_turn_completed(
        self, turn_ctx: agents.llm.ChatContext, new_message: agents.llm.ChatMessage
    ) -> None:
        sd: SessionData = self.session.userdata
        if sd.ending_requested and not self._close_scheduled:
            self._close_scheduled = True
            # NOT _fire_and_forget: that bag is cancelled by BaseGameAgent.on_exit, and
            # on_exit is what this task's own aclose() is waiting on — cancelling it from
            # inside it recursed until the close emit was never reached (bug 7a04caf1).
            # Closing the session is session-scoped work; the agent only holds the handle.
            self._close_task = asyncio.create_task(self._delayed_close())
            # Leaving the bag also left the failure unlogged: `self.session` raises
            # RuntimeError once the agent is no longer running, so a handoff inside the
            # wrap-up window would silently abandon the close — and with it the recap.
            self._close_task.add_done_callback(
                partial(log_task_failure, logger=logger, message="Delayed session close failed")
            )

    async def _delayed_close(self) -> None:
        await asyncio.sleep(CLOSE_DELAY_S)
        await self.session.aclose()

    def static_prompt(self, sd: SessionData) -> str:
        # Rebuilt from LIVE state rather than returning the constructor's instructions: the
        # exploration static layer names the current location and companion, and both change
        # within one agent instance (move_player, a companion binding).
        return build_system_prompt(sd.location_id, companion=sd.companion)

    def _build_speaker_context(
        self, speaker_id: str, player: dict, quests: list[dict], activities: list[dict], training: list[dict]
    ) -> str:
        # The id is what joins this block to the warm layer's "host player <id>" labels.
        name = sanitize_for_prompt(player["name"], max_len=100)
        hp = player["hp"]
        quest = next((f"{q['quest_name']}: {quest_objective(q)}" for q in quests if quest_objective(q)), "none")
        activity = "none"
        if activities:
            activity = activities[0].get("activity_type", "activity")
        elif training:
            activity = training[0].get("data", {}).get("program_name") or training[0]["activity_type"]
        return (
            f"[Speaker: {name} (player {speaker_id}); HP {hp['current']}/{hp['max']}; "
            f"quest step: {sanitize_for_prompt(quest, max_len=160)}; "
            f"activity: {sanitize_for_prompt(activity, max_len=80)}]"
        )

    def _build_hot_context(self, sd: SessionData) -> str:
        parts: list[str] = []

        loc_name = sd.cached_location_name or sd.location_id
        parts.append(f"[Context: {loc_name}, {sd.world_time}]")

        combat = format_combat_hot_line(sd.combat_state)
        if combat:
            parts.append(combat)

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
