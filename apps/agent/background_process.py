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

MEETING_LOCATIONS = {"accord_market_square", "accord_dockside"}

MEETING_SCENE_INSTRUCTIONS = """\
A commotion erupts near a market stall. A vendor is being hassled by a pair of rough \
dockworkers — intimidation, not violence, but escalating. A man stands nearby watching. \
Broad-shouldered, practical gear, old scars on his forearms. He clearly wants to \
intervene but is hesitating, jaw tight, hand half-reaching toward a sword he's not \
carrying today.

Narrate this scene. Do NOT name the man yet. Let the player decide what to do. \
If the player approaches, speaks up, or intervenes in any way, the man joins them. \
Together they defuse the situation — he's capable, calm under pressure, clearly trained.

After the situation resolves, he's grateful but embarrassed about hesitating. \
He introduces himself: [COMPANION_KAEL, weary]: "Kael. Thanks for stepping in. \
I should have... I used to not hesitate."

He doesn't explain further unless asked. If the player asks, he says he used to be \
a caravan guard. Doesn't elaborate on what happened.\
"""

RIDER_SCENE_INSTRUCTIONS = """\
A commotion at the edge of the market. A rider — young, dust-caked, one arm in a crude \
sling — stumbles from a horse that looks half-dead. He's desperate, scanning the crowd \
for anyone who looks like they could help. He grabs the nearest person: "The guild — \
where's the guild hall? I need to report — Hollow creatures, north of here, near \
Greyvale. Millhaven's in danger."

Narrate this scene. The rider is panicked, exhausted. Use [WOUNDED_RIDER, urgent] for \
his dialogue. He doesn't know the player — he's talking to anyone who'll listen. If \
the player approaches or responds, the rider latches onto them as someone who might \
actually do something. He gives his report: Hollow sightings, Millhaven scared, the \
old ruins glowing at night. Then he needs to sit down — he's been riding for hours.

End with the rider's information hanging in the air. Don't push the player toward the \
guild hall. Let them decide what to do with this.\
"""

GOD_WHISPER_INSTRUCTIONS = """\
Something shifts. The air thickens. Sound stops — not fades, stops, as if the world \
has held its breath. For a heartbeat, everything is impossibly still.

Then a presence. Not a voice yet, but a weight — ancient, immense, weary. It notices \
you the way a mountain notices an ant: not with contempt, but with the vast indifference \
of scale.

Two sentences from the god. Short. Weighted. Ancient perspective. Something about what \
you've found, what it means, what's coming. Then silence returns like a wave breaking, \
and the world resumes as if nothing happened.

Use your DM narrator voice — no character tags. This is environmental narration of \
something beyond mortal. The companion does NOT react during this moment. After the \
silence breaks, Kael looks shaken but says nothing unless the player speaks first.\
"""

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

GUIDANCE_LEVEL_2_SECS = 35.0
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
        self._last_guidance_time: float = 0.0
        self._quest_cache: list[dict] = []
        self._meeting_triggered: bool = False
        self._meeting_pending: bool = False
        self._meeting_init_task: asyncio.Task | None = None
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
        if self._meeting_init_task is not None:
            self._meeting_init_task.cancel()
            try:
                await self._meeting_init_task
            except asyncio.CancelledError:
                pass
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
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
            self._check_guidance()

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
                # Check for companion meeting trigger
                if not self._sd.has_companion and not self._meeting_triggered and new_loc in MEETING_LOCATIONS:
                    self._meeting_triggered = True
                    self._meeting_pending = True
                    self._queue_speech(
                        SpeechPriority.CRITICAL,
                        MEETING_SCENE_INSTRUCTIONS,
                    )
                    continue

                # Check for rider scene trigger (first session, no active quest, at market)
                # Skip if meeting scene fires or companion already present
                if (
                    not self._rider_triggered
                    and not self._meeting_triggered
                    and not self._sd.has_companion
                    and new_loc == "accord_market_square"
                    and not self._quest_cache
                ):
                    self._rider_triggered = True
                    self._queue_speech(
                        SpeechPriority.CRITICAL,
                        RIDER_SCENE_INSTRUCTIONS,
                    )
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

    async def _initialize_companion_after_meeting(self) -> None:
        """Initialize companion state after the meeting scene fires."""
        # Short delay to let the meeting speech play out
        await asyncio.sleep(5.0)
        try:
            from session_data import CompanionState

            self._sd.companion = CompanionState(
                id="companion_kael",
                name="Kael",
                last_speech_time=time.time(),
            )
            await db.set_player_flag(self._sd.player_id, "companion_met", True)
            # Rebuild warm layer to include companion context
            await self._rebuild_warm_layer()
            logger.info("Companion Kael initialized after meeting scene")
        except Exception:
            logger.warning("Failed to initialize companion after meeting", exc_info=True)

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

    def _check_guidance(self) -> None:
        if self._sd.in_combat:
            return

        if self._sd.last_player_speech_time <= 0:
            return

        # Don't nudge again if player hasn't spoken since last nudge
        if self._last_guidance_time >= self._sd.last_player_speech_time:
            return

        baseline = max(self._sd.last_player_speech_time, self._sd.last_agent_speech_end)
        silence = time.time() - baseline

        if silence >= GUIDANCE_LEVEL_2_SECS:
            self._last_guidance_time = time.time()
            hints = self._get_quest_hints()
            hint_text = f" Consider using this hint: {hints[0]}" if hints else ""
            if self._sd.companion_can_act and self._sd.companion:
                self._sd.companion.last_speech_time = time.time()
                self._queue_speech(
                    SpeechPriority.IMPORTANT,
                    "The player has been quiet for a while. Kael offers a gentle "
                    "practical suggestion about what to do next — one sentence. "
                    f"Use [COMPANION_KAEL, {self._sd.companion.emotional_state}] tag.{hint_text}",
                )
            else:
                self._queue_speech(
                    SpeechPriority.IMPORTANT,
                    "The player has been quiet for a while. Have a companion "
                    "offer a gentle suggestion about what to do next — "
                    f"one sentence, in character.{hint_text}",
                )

    def _get_quest_hints(self) -> list[str]:
        """Pull hints from cached quest data in recent events."""
        if not self._quest_cache:
            return []
        for quest in self._quest_cache:
            current_stage = quest.get("current_stage", 0)
            global_hints = quest.get("global_hints", {})
            hint_key = f"stuck_stage_{current_stage + 1}"
            hint = global_hints.get(hint_key)
            if hint:
                return [hint]
        return []

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
            if self._meeting_pending:
                self._meeting_pending = False
                self._meeting_init_task = asyncio.create_task(self._initialize_companion_after_meeting())
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
