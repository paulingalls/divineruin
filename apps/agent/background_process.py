"""Background process: event loop, warm layer rebuild, proactive speech, guidance."""

from __future__ import annotations

import asyncio
import enum
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import db
import event_types as E
from event_bus import GameEvent
from god_whisper_data import get_god_profile, should_trigger_whisper
from prompts import build_full_prompt, build_system_prompt, build_warm_layer, quest_objective
from sanitize import sanitize_for_prompt
from tools import _disposition_rank

if TYPE_CHECKING:
    from livekit.agents import Agent, AgentSession

    from session_data import SessionData

logger = logging.getLogger("divineruin.background")

REBUILD_EVENT_TYPES = {
    E.LOCATION_CHANGED,
    E.QUEST_UPDATED,
    E.DISPOSITION_CHANGED,
    E.COMBAT_STARTED,
    E.COMBAT_ENDED,
    E.HOLLOW_CORRUPTION_CHANGED,
    E.DIVINE_FAVOR_CHANGED,
}


CORRUPTION_COMPANION_SPEECH: dict[int, str] = {
    1: (
        "Kael tenses and looks around slowly. Have him make one quiet observation: "
        "something about the silence, the wrongness, how the air feels different. "
        "One sentence. Use [COMPANION_KAEL, uneasy] tag."
    ),
    2: (
        "Kael is visibly on edge. Have him react to the corruption — something about sounds "
        "coming from wrong directions, distances feeling off. Shorter sentence. More tense. "
        "Use [COMPANION_KAEL, nervous] tag."
    ),
    3: (
        "Kael is deeply unsettled. One short, urgent sentence. He doesn't elaborate — "
        "just names what he's feeling. Use [COMPANION_KAEL, urgent] tag."
    ),
}

COMPANION_IDLE_SECS = 45.0

TIMER_FALLBACK_SECS = 30.0


class SpeechPriority(enum.IntEnum):
    ROUTINE = 0
    IMPORTANT = 1
    CRITICAL = 2


@dataclass(order=True)
class PendingSpeech:
    priority: SpeechPriority
    instructions: str = field(compare=False)
    created: float = field(default_factory=time.time, compare=False)
    stinger_sound: str | None = field(default=None, compare=False)


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
        rider = await db.get_scene("scene_rider_arrival")
        if rider:
            self._scene_cache["scene_rider_arrival"] = rider

        # Initial warm layer build
        await self._rebuild_warm_layer()
        logger.info("Background process started")

        while not self._stop:
            event = await self._sd.event_bus.get(timeout=TIMER_FALLBACK_SECS)

            events: list[GameEvent] = []
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

    def _handle_events(self, events: list[GameEvent]) -> bool:
        needs_rebuild = False
        can_act = self._sd.companion_can_act
        companion = self._sd.companion

        for ev in events:
            if ev.event_type in REBUILD_EVENT_TYPES:
                needs_rebuild = True

            if ev.event_type == E.LOCATION_CHANGED:
                new_loc = ev.payload.get("new_location", "")

                # Check for rider scene trigger (first session, no active quest, at market)
                if (
                    not self._rider_triggered
                    and not self._sd.has_companion
                    and new_loc == "accord_market_square"
                    and not self._quest_cache
                ):
                    self._rider_triggered = True
                    rider_scene = self._scene_cache.get("scene_rider_arrival")
                    if rider_scene:
                        self._queue_speech(SpeechPriority.CRITICAL, rider_scene["instructions"])
                    continue

                if can_act and companion:
                    companion.emotional_state = "curious"
                    self._queue_speech(
                        SpeechPriority.IMPORTANT,
                        f"The player just arrived at a new location ({new_loc}). "
                        f"Kael looks around. Have him make one brief observation about "
                        f"the new surroundings. Use [COMPANION_KAEL, {companion.emotional_state}] tag.",
                    )
                else:
                    self._queue_speech(
                        SpeechPriority.IMPORTANT,
                        f"The player just arrived at a new location ({new_loc}). Describe the atmosphere briefly.",
                    )

            elif ev.event_type == E.QUEST_UPDATED:
                quest_name = sanitize_for_prompt(ev.payload.get("quest_name", "unknown quest"), max_len=100)
                objective = sanitize_for_prompt(ev.payload.get("objective", ""), max_len=200)
                if can_act and companion:
                    companion.emotional_state = "focused"
                    self._queue_speech(
                        SpeechPriority.IMPORTANT,
                        f"The quest '{quest_name}' just progressed. New objective: {objective}. "
                        "Kael reacts to the quest progression. One sentence. "
                        "Use [COMPANION_KAEL, focused] tag.",
                    )
                else:
                    self._queue_speech(
                        SpeechPriority.IMPORTANT,
                        f"The quest '{quest_name}' just progressed. New objective: {objective}.",
                    )

            elif ev.event_type == E.COMBAT_ENDED:
                outcome = ev.payload.get("outcome", "victory")
                if outcome == "victory":
                    if can_act and companion:
                        companion.emotional_state = "relieved"
                        self._queue_speech(
                            SpeechPriority.IMPORTANT,
                            "Combat has ended in victory. Catch your breath. "
                            "Describe the aftermath — the quiet after violence. "
                            "Kael catches his breath and checks if you're okay. "
                            "One sentence. Use [COMPANION_KAEL, relieved] tag.",
                        )
                    elif self._sd.has_companion and companion and not companion.is_conscious:
                        companion.is_conscious = True
                        companion.emotional_state = "weary"
                        self._queue_speech(
                            SpeechPriority.IMPORTANT,
                            "Combat has ended in victory. Kael stirs, groaning. "
                            "First thing he does is check if you're okay. "
                            "Use [COMPANION_KAEL, weary] tag.",
                        )
                    else:
                        self._queue_speech(
                            SpeechPriority.IMPORTANT,
                            "Combat has ended in victory. Catch your breath. "
                            "Describe the aftermath — the quiet after violence.",
                        )
                elif outcome == "defeat":
                    self._queue_speech(
                        SpeechPriority.CRITICAL,
                        "The player has fallen in combat. This is a dramatic moment. Narrate the darkness closing in.",
                    )

            elif ev.event_type == E.DISPOSITION_CHANGED:
                if can_act and companion:
                    npc_name = sanitize_for_prompt(ev.payload.get("npc_name", "someone"), max_len=100)
                    new_disp = ev.payload.get("new", "neutral")
                    prev_disp = ev.payload.get("previous", "neutral")
                    delta_positive = _disposition_rank(new_disp) > _disposition_rank(prev_disp)
                    if delta_positive:
                        companion.emotional_state = "pleased"
                        reaction = "approves"
                    else:
                        companion.emotional_state = "troubled"
                        reaction = "is uncomfortable"
                    self._queue_speech(
                        SpeechPriority.ROUTINE,
                        f"Kael {reaction} of the player's interaction with {npc_name}. "
                        f"One sentence. Use [COMPANION_KAEL, {companion.emotional_state}] tag.",
                    )

            elif ev.event_type == E.HOLLOW_CORRUPTION_CHANGED:
                level = ev.payload.get("level", 0)
                if level > 0 and can_act and companion:
                    speech = CORRUPTION_COMPANION_SPEECH.get(level)
                    if speech:
                        self._queue_speech(SpeechPriority.IMPORTANT, speech)

            elif ev.event_type == E.WORLD_EVENT:
                event_id = ev.payload.get("event_id", "")
                if event_id.startswith("god_whisper"):
                    self._queue_god_whisper(ev.payload)

            elif ev.event_type == E.DIVINE_FAVOR_CHANGED:
                new_level = ev.payload.get("new_level", 0)
                last_whisper = ev.payload.get("last_whisper_level", 0)
                if should_trigger_whisper(new_level, last_whisper):
                    self._queue_god_whisper(ev.payload)

        return needs_rebuild

    def _queue_god_whisper(self, payload: dict) -> None:
        """Build god-specific whisper instructions and queue as CRITICAL."""
        patron_id = payload.get("patron_id") or self._sd.patron_id
        profile = get_god_profile(patron_id)
        instructions = self._build_god_whisper_instructions(profile, payload)
        self._speech_queue.append(
            PendingSpeech(
                priority=SpeechPriority.CRITICAL,
                instructions=instructions,
                stinger_sound=profile.stinger_sound,
            )
        )

    @staticmethod
    def _build_god_whisper_instructions(profile, payload: dict) -> str:
        """Build full instruction string for god whisper delivery."""
        context = payload.get("reason", "")
        return (
            "Something shifts. The air thickens. Sound stops — not fades, stops, as if the world "
            "has held its breath. For a heartbeat, everything is impossibly still.\n\n"
            "Then a presence. Not a voice yet, but a weight — ancient, immense. "
            "Narrate this atmospheric shift in your DM narrator voice.\n\n"
            f"Then the god speaks. Use [{profile.voice_character}, {profile.voice_emotion}] tag. "
            f"Speaking style: {profile.speaking_style}. "
            f"{profile.personality_prompt}\n\n"
            "Two sentences from the god. Short. Weighted. Ancient perspective. "
            f"{f'Context: {context}. ' if context else ''}"
            "Then silence returns like a wave breaking, and the world resumes. "
            "The companion does NOT react during this moment. After the silence breaks, "
            "Kael looks shaken but says nothing unless the player speaks first."
        )

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

        from tools import get_active_scene_for_context

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
                    favor = await db.get_divine_favor(self._sd.player_id)
                    if favor:
                        await db.mark_favor_whisper_level(self._sd.player_id, favor.get("level", 0))
                except Exception:
                    logger.warning("Failed to mark favor whisper level", exc_info=True)
            if "COMPANION_KAEL" in top.instructions and self._sd.companion:
                self._sd.companion.last_speech_time = time.time()
        except Exception:
            logger.warning("Failed to deliver proactive speech", exc_info=True)

    async def _rebuild_warm_layer(self) -> None:
        try:
            quests, location, npcs_raw = await asyncio.gather(
                db.get_active_player_quests(self._sd.player_id),
                db.get_location(self._sd.location_id),
                db.get_npcs_at_location(self._sd.location_id),
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
                self._scene_cache = await db.get_scenes_batch(scene_ids)
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

            region_type = getattr(self._agent, "_agent_type", "city")
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
                region_type=region_type,
                scene_cache=self._scene_cache or None,
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
            self._cached_static = build_system_prompt(
                self._sd.location_id, companion=self._sd.companion, region_type=region_type
            )
        full_prompt = build_full_prompt(self._cached_static, warm)
        await self._agent.update_instructions(full_prompt)
        logger.info("Warm layer updated (%d chars)", len(warm))
