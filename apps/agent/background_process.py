"""Background process: event loop, warm layer rebuild, proactive speech, guidance."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

import db_activity_queries
import db_content_queries
import db_mutations_divine
import db_queries
import db_training
import event_types as E
from bg_event_handlers import handle_events
from bg_speech import COMPANION_IDLE_SECS, PendingSpeech, SpeechPriority
from sanitize import sanitize_for_prompt
from system_prompts import build_system_prompt
from warm_prompts import build_full_prompt, build_warm_layer, quest_objective

if TYPE_CHECKING:
    from livekit.agents import Agent, AgentSession

    from session_data import SessionData

logger = logging.getLogger("divineruin.background")

TIMER_FALLBACK_SECS = 30.0


class BackgroundProcess:
    def __init__(
        self,
        agent: Agent,
        session: AgentSession,
        session_data: SessionData,
    ) -> None:
        self._agent = agent
        self._session = session
        self._sd = session_data
        self._task: asyncio.Task | None = None
        self._last_warm_layer: str = ""
        self._speech_queue: list[PendingSpeech] = []
        self._stop = False
        self._quest_cache: list[dict] = []
        self._scene_cache: dict[str, dict] = {}
        self._scene_hint_state: dict = {}
        self._rider_triggered: bool = False
        self._last_static_key: tuple[str, bool] | None = None
        self._cached_static: str = ""
        self._paused: bool = False

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    async def stop(self) -> None:
        self._stop = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        # Pre-fetch event scenes into cache
        rider = await db_content_queries.get_scene("scene_rider_arrival")
        if rider:
            self._scene_cache["scene_rider_arrival"] = rider

        # Initial warm layer build
        await self._rebuild_warm_layer()
        logger.info("Background process started")

        while not self._stop:
            event = await self._sd.event_bus.get(timeout=TIMER_FALLBACK_SECS)

            events = []
            if event is not None:
                events.append(event)
            events.extend(self._sd.event_bus.drain())

            needs_rebuild = self._handle_events(events)

            if needs_rebuild or event is None:
                await self._rebuild_warm_layer()

            if self._paused:
                continue

            self._check_companion_idle()
            self._check_scene_beat_hints()

            await self._deliver_speech()

    def _handle_events(self, events: list) -> bool:
        needs_rebuild, self._rider_triggered = handle_events(
            events,
            self._sd,
            self._speech_queue,
            self._rider_triggered,
            self._scene_cache,
            self._quest_cache,
        )
        return needs_rebuild

    def _check_companion_idle(self) -> None:
        if not self._sd.companion_can_act:
            return
        companion = self._sd.companion
        if companion is None:
            return
        if self._sd.in_combat:
            return
        if companion.last_speech_time <= 0:
            return

        silence = time.time() - companion.last_speech_time
        if silence >= COMPANION_IDLE_SECS:
            companion.last_speech_time = time.time()
            self._queue_speech(
                SpeechPriority.ROUTINE,
                "Kael makes an idle observation about the surroundings or something on his mind. "
                f"One sentence. Use [COMPANION_KAEL, {companion.emotional_state}] tag.",
            )

    def _check_scene_beat_hints(self) -> None:
        """Deliver companion hints from the active scene's beats on player silence."""
        if self._sd.in_combat:
            return
        if self._sd.last_player_speech_time <= 0:
            return

        from scene_tools import get_active_scene_for_context

        scene = get_active_scene_for_context(self._scene_cache, self._quest_cache, None)
        if scene is None:
            return

        beats = scene.get("beats", [])
        if not beats:
            return

        # Reset hint state if scene changed
        state = self._scene_hint_state
        if state.get("scene_id") != scene["id"]:
            self._scene_hint_state = {
                "scene_id": scene["id"],
                "beat_index": 0,
                "hint_index": 0,
                "last_hint_time": 0.0,
            }
            state = self._scene_hint_state

        beat_idx = state["beat_index"]
        if beat_idx >= len(beats):
            return  # all beats exhausted

        beat = beats[beat_idx]
        hints = beat.get("companion_hints", [])
        hint_idx = state["hint_index"]

        if hint_idx >= len(hints):
            # Advance to next beat
            state["beat_index"] += 1
            state["hint_index"] = 0
            state["last_hint_time"] = 0.0
            return

        delay = beat.get("hint_delay_seconds", 45)

        # Silence baseline: max of player speech, agent speech, and last hint delivery
        baseline = max(self._sd.last_player_speech_time, self._sd.last_agent_speech_end)
        if state["last_hint_time"] > 0:
            baseline = max(baseline, state["last_hint_time"])

        silence = time.time() - baseline
        if silence < delay:
            return

        # Deliver hint
        hint_text = hints[hint_idx]
        state["hint_index"] = hint_idx + 1
        state["last_hint_time"] = time.time()

        if self._sd.companion_can_act and self._sd.companion:
            self._sd.companion.last_speech_time = time.time()
            self._queue_speech(
                SpeechPriority.IMPORTANT,
                f"Kael offers guidance: {hint_text} Use [COMPANION_KAEL, {self._sd.companion.emotional_state}] tag.",
            )

    def _queue_speech(self, priority: SpeechPriority, instructions: str) -> None:
        self._speech_queue.append(PendingSpeech(priority=priority, instructions=instructions))

    async def _deliver_speech(self) -> None:
        if not self._speech_queue:
            return

        top = max(self._speech_queue)
        self._speech_queue.clear()

        try:
            # Fire stinger SFX before god whisper speech
            if top.stinger_sound is not None:
                from game_events import publish_game_event

                await publish_game_event(
                    self._sd.room,
                    E.PLAY_SOUND,
                    {"sound_name": top.stinger_sound},
                    event_bus=self._sd.event_bus,
                )
                await asyncio.sleep(2.0)

            await self._session.generate_reply(instructions=top.instructions)
            logger.info("Proactive speech delivered (priority=%s)", top.priority.name)

            # Mark last_whisper_level after delivering (deferred from critical path)
            if top.stinger_sound is not None:
                try:
                    favor = await db_activity_queries.get_divine_favor(self._sd.player_id)
                    if favor:
                        await db_mutations_divine.mark_favor_whisper_level(self._sd.player_id, favor.get("level", 0))
                except Exception:
                    logger.warning("Failed to mark favor whisper level", exc_info=True)
            if "COMPANION_KAEL" in top.instructions and self._sd.companion:
                self._sd.companion.last_speech_time = time.time()
        except Exception:
            logger.warning("Failed to deliver proactive speech", exc_info=True)

    async def _rebuild_warm_layer(self) -> None:
        try:
            quests, location, npcs_raw, training = await asyncio.gather(
                db_queries.get_active_player_quests(self._sd.player_id),
                db_content_queries.get_location(self._sd.location_id),
                db_queries.get_npcs_at_location(self._sd.location_id),
                db_training.get_player_training_activities(self._sd.player_id, state=None),
            )
            self._quest_cache = quests

            # Build scene cache from quest scene_graphs
            scene_ids: list[str] = []
            for q in quests:
                for entry in q.get("scene_graph", []):
                    sid = entry.get("scene_id")
                    if sid and sid not in scene_ids:
                        scene_ids.append(sid)
            if scene_ids:
                self._scene_cache = await db_content_queries.get_scenes_batch(scene_ids)
            else:
                self._scene_cache = {}
        except Exception:
            logger.debug("Warm layer data fetch failed", exc_info=True)
            return

        try:
            # Update hot context caches on SessionData (read by voice loop, zero I/O)
            if location:
                self._sd.cached_location_name = location.get("name", self._sd.location_id)
            else:
                self._sd.cached_location_name = self._sd.location_id
            self._sd.cached_npc_names = [
                sanitize_for_prompt(n.get("name", n.get("id", "?")), max_len=100) for n in (npcs_raw or [])
            ]

            self._sd.cached_quest_summaries = [
                f"{sanitize_for_prompt(q['quest_name'], max_len=100)}: {sanitize_for_prompt(quest_objective(q))}"
                for q in (self._quest_cache or [])
                if quest_objective(q)
            ]

            warm = await build_warm_layer(
                self._sd.location_id,
                self._sd.player_id,
                self._sd.world_time,
                combat_state=self._sd.combat_state,
                companion=self._sd.companion,
                quests=self._quest_cache or None,
                corruption_level=self._sd.corruption_level,
                location=location,
                npcs_raw=npcs_raw,
                scene_cache=self._scene_cache or None,
                training=training or None,
            )
        except Exception:
            logger.warning("Warm layer build failed", exc_info=True)
            return

        if warm == self._last_warm_layer:
            return

        self._last_warm_layer = warm
        static_key = (self._sd.location_id, self._sd.has_companion)
        if static_key != self._last_static_key:
            self._last_static_key = static_key
            self._cached_static = build_system_prompt(self._sd.location_id, companion=self._sd.companion)
        full_prompt = build_full_prompt(self._cached_static, warm)
        await self._agent.update_instructions(full_prompt)
        logger.info("Warm layer updated (%d chars)", len(warm))
