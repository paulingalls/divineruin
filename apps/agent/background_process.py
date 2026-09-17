"""Background process: event loop, warm layer rebuild, proactive speech, guidance."""

from __future__ import annotations

import asyncio
import logging
import time
from functools import partial
from typing import TYPE_CHECKING, cast

import asyncpg

import db_activity_queries
import db_content_queries
import db_mutations_divine
import db_queries
import db_training
import event_types as E
from bg_event_handlers import handle_events
from bg_speech import COMPANION_IDLE_SECS, PendingSpeech, SpeechPriority
from companion_cue_events import publish_companion_cue
from sanitize import sanitize_for_prompt
from session_end import run_session_end
from speech_delivery import deliver_speech
from system_prompts import build_companion_cue, is_companion_cue
from task_logging import log_task_failure
from warm_prompts import build_full_prompt, build_warm_layer, quest_objective

if TYPE_CHECKING:
    from livekit.agents import AgentSession

    from base_agent import BaseGameAgent
    from session_data import SessionData

logger = logging.getLogger("divineruin.background")

TIMER_FALLBACK_SECS = 30.0
TRANSIENT_IO_ERRORS = (OSError, TimeoutError, asyncpg.PostgresError, asyncpg.InterfaceError)


class BackgroundProcess:
    def __init__(
        self,
        session: AgentSession,
        session_data: SessionData,
    ) -> None:
        # No agent here on purpose: the process outlives every mode handoff, so it resolves
        # the CURRENT agent at injection time (_apply_warm). One built for the exploration
        # agent would keep writing the warm layer into an agent that no longer holds the floor.
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
        self._last_static_key: tuple[str, str, str | None] | None = None
        self._cached_static: str = ""
        self._last_target: BaseGameAgent | None = None
        self._paused: bool = False

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())
        self._task.add_done_callback(partial(log_task_failure, logger=logger, message="Background process failed"))
        # The session is the owner, so the session's end is the only thing that stops the loop —
        # an agent's on_exit is a handoff, not a session end (debt 2009d9ef).
        self._session.on("close", self._on_session_close)
        # ...and the same reasoning puts the end-of-session recap here. start() is called from
        # ExplorationAgent.on_enter's `if sd.background is None:` block, so a handback registers
        # nothing new and the recap fires exactly once per session. Its own handler, not folded
        # into _on_session_close: stop() calls that one directly to join the loop, and a recap
        # there would run an LLM call and a DB write from inside the fast lane.
        self._session.on("close", self._on_session_end)

    def _on_session_close(self, _ev: object) -> None:
        """Sync half of ``stop`` — LiveKit emits ``close`` from a sync handler chain."""
        self._stop = True
        if self._task is not None:
            self._task.cancel()

    def _on_session_end(self, _ev: object) -> None:
        """Spawn the end-of-session recap. ``emit`` is synchronous (rtc/event_emitter.py), so
        this cannot await; ``agent._join_session_end`` joins the handle before room teardown."""
        self._sd.session_end_task = asyncio.create_task(run_session_end(self._sd))

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    async def stop(self) -> None:
        """Awaitable twin of ``_on_session_close``, for callers that can wait for the loop.

        No production caller: the session's ``close`` handler is the whole shutdown path now.
        Tests use this to join the loop before the event loop goes away.
        """
        self._on_session_close(None)
        if self._task is not None:
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        try:
            rider = await db_content_queries.get_scene("scene_rider_arrival")
            if rider:
                self._scene_cache["scene_rider_arrival"] = rider
        except TRANSIENT_IO_ERRORS:
            logger.error("Rider scene prefetch failed", exc_info=True)

        # Initial warm layer build
        await self._rebuild_warm_layer()
        logger.info("Background process started")

        while not self._stop:
            event = await self._sd.event_bus.get(timeout=TIMER_FALLBACK_SECS)

            events = []
            if event is not None:
                events.append(event)
            events.extend(self._sd.event_bus.drain())

            await self._process_events(events, timed_out=event is None)

            if self._paused:
                continue

            self._check_companion_idle()
            self._check_scene_beat_hints()

            await self._deliver_speech()

    async def _process_events(self, events: list, timed_out: bool) -> None:
        needs_rebuild = self._handle_events(events)
        if needs_rebuild or timed_out:
            await self._rebuild_warm_layer()

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
                build_companion_cue(
                    companion,
                    "makes an idle observation about the surroundings or something on their mind.",
                    companion.emotional_state,
                ),
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
                build_companion_cue(
                    self._sd.companion,
                    f"offers this guidance: {hint_text}",
                    self._sd.companion.emotional_state,
                ),
            )

    def _queue_speech(self, priority: SpeechPriority, instructions: str) -> None:
        self._speech_queue.append(PendingSpeech(priority=priority, instructions=instructions))

    async def _deliver_speech(self) -> None:
        if not self._speech_queue:
            return

        # A fight HOLDS proactive speech. The loop is session-scoped since story-023, so it runs
        # through combat now, and the DM is mid-beat with the phase loop owning the floor — the
        # same reason _check_companion_idle and _check_scene_beat_hints refuse to produce here.
        # Held rather than dropped: an event cue is one-shot, so discarding it loses the
        # announcement outright, where the idle/hint producers are remade by their own timers.
        speakable, held = self._speech_queue, []
        if self._sd.in_combat:
            speakable = [s for s in self._speech_queue if s.combat_safe]
            held = [s for s in self._speech_queue if not s.combat_safe]
        if not speakable:
            return

        # Newest wins a tie, which matters only because of the hold above: `max` returns the FIRST
        # maximal element, so a cue carried through the whole fight would outrank the same-priority
        # cue the fight's END raises — on a defeat, a held god whisper spoken in place of "the
        # player has fallen". At equal urgency the most recent event is the one the player is in.
        top = max(speakable, key=lambda s: (s.priority, s.created))
        self._speech_queue = held

        companion = self._sd.companion
        if companion and is_companion_cue(top.instructions, companion):
            await publish_companion_cue(self._sd, companion)

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

        delivered = await deliver_speech(
            self._session,
            top.instructions,
            logger,
            f"Proactive speech (priority={top.priority.name})",
        )
        if not delivered:
            return

        logger.info("Proactive speech delivered (priority=%s)", top.priority.name)

        # Mark last_whisper_level after delivering (deferred from critical path)
        if top.stinger_sound is not None:
            try:
                favor = await db_activity_queries.get_divine_favor(self._sd.player_id)
                if favor:
                    await db_mutations_divine.mark_favor_whisper_level(self._sd.player_id, favor.get("level", 0))
            except TRANSIENT_IO_ERRORS:
                logger.warning("Failed to mark favor whisper level", exc_info=True)
        if self._sd.companion and is_companion_cue(top.instructions, self._sd.companion):
            self._sd.companion.last_speech_time = time.time()

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
        except TRANSIENT_IO_ERRORS:
            logger.error("Warm layer data fetch failed", exc_info=True)
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

            base = await build_warm_layer(
                self._sd.location_id,
                self._sd.player_id,
                self._sd.world_time,
                companion=self._sd.companion,
                quests=self._quest_cache or None,
                corruption_level=self._sd.corruption_level,
                location=location,
                npcs_raw=npcs_raw,
                scene_cache=self._scene_cache or None,
                training=training or None,
            )
        except TRANSIENT_IO_ERRORS:
            logger.error("Warm layer build failed", exc_info=True)
            return

        await self._apply_warm(base)

    async def _apply_warm(self, warm: str) -> None:
        # Every agent that can hold the floor while this process runs is a BaseGameAgent; one
        # that is not raises on static_prompt rather than being quietly skipped.
        agent = cast("BaseGameAgent", self._session.current_agent)
        # The target is half the dedupe key: a handoff hands the floor to an agent whose
        # instructions carry no warm layer at all, and an unchanged warm string must still
        # reach it.
        if warm == self._last_warm_layer and agent is self._last_target:
            return

        self._last_warm_layer = warm
        self._last_target = agent
        # Keyed on companion IDENTITY, not merely presence: the static layer renders the
        # assigned companion's own name, tag and profile, so a bool would serve a stale
        # section if the bound companion ever changed within a session. Keyed on the agent
        # too: each agent's static half is its own (COMBAT_SYSTEM_PROMPT for a fight).
        companion = self._sd.companion
        static_key = (
            type(agent).__name__,
            self._sd.location_id,
            companion.id if self._sd.has_companion and companion else None,
        )
        if static_key != self._last_static_key:
            self._last_static_key = static_key
            self._cached_static = agent.static_prompt(self._sd)
        full_prompt = build_full_prompt(self._cached_static, warm)
        await agent.update_instructions(full_prompt)
        logger.info("Warm layer updated (%d chars) for %s", len(warm), type(agent).__name__)
