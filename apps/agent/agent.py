import asyncio
import json
import logging
import os
import re
import time
from collections.abc import AsyncGenerator, AsyncIterable
from typing import Any

from livekit import agents, rtc
from livekit.agents import Agent, AgentServer, AgentSession, ModelSettings, stt
from livekit.agents.stt import SpeechEventType
from livekit.plugins import anthropic, deepgram, inworld, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

import db
from affect_analyzer import PlayerAffectAnalyzer
from background_process import BackgroundProcess
from dialogue_parser import parse_dialogue_stream
from game_events import publish_game_event
from latency import TurnTimer
from prompts import build_system_prompt, format_affect_context, quest_objective
from rules_engine import hp_threshold_status
from session_data import CompanionState, SessionData
from tools import (
    add_to_inventory,
    award_xp,
    discover_hidden_element,
    end_combat,
    enter_location,
    move_player,
    play_sound,
    query_inventory,
    query_location,
    query_lore,
    query_npc,
    remove_from_inventory,
    request_attack,
    request_death_save,
    request_saving_throw,
    request_skill_check,
    resolve_enemy_turn,
    roll_dice,
    start_combat,
    update_npc_disposition,
    update_quest,
)
from transcript import TranscriptLogger
from voices import VOICES, get_voice_config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("divineruin.dm")

REQUIRED_ENV_VARS = [
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "ANTHROPIC_API_KEY",
    "DEEPGRAM_API_KEY",
    "INWORLD_API_KEY",
    "DATABASE_URL",
    "REDIS_URL",
]

WORLD_TOOLS = [enter_location, query_location, query_npc, query_lore, query_inventory, discover_hidden_element]
MECHANICS_TOOLS = [request_skill_check, request_attack, request_saving_throw, roll_dice, play_sound]
MUTATION_TOOLS = [move_player, add_to_inventory, remove_from_inventory, update_quest, award_xp, update_npc_disposition]
COMBAT_TOOLS = [start_combat, resolve_enemy_turn, request_death_save, end_combat]
ALL_TOOLS = WORLD_TOOLS + MECHANICS_TOOLS + MUTATION_TOOLS + COMBAT_TOOLS


def validate_env() -> None:
    missing = [v for v in REQUIRED_ENV_VARS if not os.getenv(v)]
    empty_voices = [k for k, v in VOICES.items() if not v]
    if empty_voices:
        logger.warning("Voice IDs not set for: %s", ", ".join(empty_voices))
    if missing:
        raise OSError(f"Missing required environment variables: {', '.join(missing)}")


START_LOCATION = "accord_guild_hall"


class DungeonMasterAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=build_system_prompt(START_LOCATION),
            tools=ALL_TOOLS,
        )
        self._turn_timer = TurnTimer()
        self._background: BackgroundProcess | None = None
        self._affect_analyzer = PlayerAffectAnalyzer()
        self._transcript: TranscriptLogger | None = None
        self._bg_tasks: set[asyncio.Task[None]] = set()
        self._session_start_time: float = time.time()

    def _fire_and_forget(self, coro: Any) -> None:
        task = asyncio.create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._on_bg_task_done)

    def _on_bg_task_done(self, task: asyncio.Task[None]) -> None:
        self._bg_tasks.discard(task)
        if not task.cancelled() and task.exception():
            logger.error("Background task failed", exc_info=task.exception())

    async def _publish_session_init(self, sd: SessionData) -> None:
        try:
            payload = await db.get_session_init_payload(sd.player_id)
            await publish_game_event(sd.room, "session_init", payload, sd.event_bus)
        except Exception:
            logger.exception("Failed to publish session_init")

    async def on_enter(self) -> None:
        logger.info("DM agent entered session")
        self._session_start_time = time.time()
        self._affect_analyzer.start()
        sd: SessionData = self.session.userdata
        self._transcript = TranscriptLogger(sd.room, sd.event_bus)
        self._background = BackgroundProcess(
            agent=self,
            session=self.session,
            session_data=sd,
        )
        self._background.start()

        self._fire_and_forget(self._publish_session_init(sd))

    async def on_exit(self) -> None:
        logger.info("DM agent exiting session")
        sd: SessionData = self.session.userdata

        # Cancel in-flight background tasks (transcript writes, etc.)
        # before closing resources they depend on.
        for task in list(self._bg_tasks):
            task.cancel()
        if self._bg_tasks:
            await asyncio.gather(*self._bg_tasks, return_exceptions=True)

        elapsed = time.time() - self._session_start_time
        recent = list(sd.recent_events)[-5:] if sd.recent_events else []
        summary_text = " ".join(recent) if recent else "A brief venture into the world."

        summary_payload = {
            "summary": summary_text,
            "xp_earned": 0,
            "items_found": [],
            "quest_progress": [],
            "duration": round(elapsed),
            "next_hooks": [],
        }

        results = await asyncio.gather(
            publish_game_event(sd.room, "session_end", summary_payload, sd.event_bus),
            db.save_session_summary(sd.player_id, sd.session_id, summary_payload),
            return_exceptions=True,
        )
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                labels = ("publish session_end", "save session summary")
                logger.exception("Failed to %s", labels[i], exc_info=result)

        try:
            await self._affect_analyzer.stop()
        except Exception:
            logger.exception("Failed to stop affect analyzer")
        try:
            if self._background:
                await self._background.stop()
        except Exception:
            logger.exception("Failed to stop background process")
        if self._transcript:
            self._transcript.close()

    async def stt_node(
        self,
        audio: AsyncIterable[rtc.AudioFrame],
        model_settings: ModelSettings,
    ) -> AsyncGenerator[stt.SpeechEvent | str, None]:
        """Override stt_node to fork STT events to the affect analyzer."""
        # Phase A: pass audio through unchanged (Phase B adds audio forking)
        async for event in Agent.default.stt_node(self, audio, model_settings):
            if isinstance(event, stt.SpeechEvent) and event.type == SpeechEventType.FINAL_TRANSCRIPT:
                self._affect_analyzer.enqueue_event(event)
                if self._transcript and event.alternatives:
                    self._fire_and_forget(self._transcript.log_player(event.alternatives[0].text))
            yield event

    async def on_user_turn_completed(
        self, turn_ctx: agents.llm.ChatContext, new_message: agents.llm.ChatMessage
    ) -> None:
        self._turn_timer.start()
        self._turn_timer.mark("user_turn_end")

        sd: SessionData = self.session.userdata
        sd.last_player_speech_time = time.time()

        try:
            hot = await self._build_hot_context(sd)
        except Exception:
            logger.exception("Failed to build hot context")
            hot = ""
        if hot:
            turn_ctx.add_message(role="assistant", content=hot)

        affect = self._affect_analyzer.get_current_vector()
        if affect:
            turn_ctx.add_message(role="assistant", content=format_affect_context(affect))

    async def _build_hot_context(self, sd: SessionData) -> str:
        parts: list[str] = []

        location, quests, npcs = await asyncio.gather(
            db.get_location(sd.location_id),
            db.get_active_player_quests(sd.player_id),
            db.get_npcs_at_location(sd.location_id),
        )

        # Current location + time
        loc_name = location.get("name", sd.location_id) if location else sd.location_id
        parts.append(f"[Context: {loc_name}, {sd.world_time}]")

        # Combat state
        if sd.combat_state is not None:
            cs = sd.combat_state
            combatants = []
            for pid in cs.initiative_order:
                p = cs.get_participant(pid)
                if p is not None:
                    status = hp_threshold_status(p.hp_current, p.hp_max)
                    combatants.append(f"{p.name}({status})")
            parts.append(f"[COMBAT Round {cs.round_number}: {', '.join(combatants)}]")

        # Active quest objectives
        if quests:
            objectives = [f"{q['quest_name']}: {quest_objective(q)}" for q in quests if quest_objective(q)]
            if objectives:
                parts.append("[Quests: " + "; ".join(objectives) + "]")

        # Recent events
        if sd.recent_events:
            recent = list(sd.recent_events)[-3:]
            parts.append("[Recent: " + "; ".join(recent) + "]")

        # NPCs nearby
        if npcs:
            names = [n.get("name", n.get("id", "?")) for n in npcs]
            parts.append("[NPCs nearby: " + ", ".join(names) + "]")

        return " ".join(parts)

    async def tts_node(
        self, text: AsyncIterable[str], model_settings: ModelSettings
    ) -> AsyncGenerator[rtc.AudioFrame, None]:
        self._turn_timer.mark("tts_start")
        first_frame = True

        buffered_text = ""
        buffered_character = ""
        buffered_emotion = ""

        async def synthesize_chunk(chunk: str) -> AsyncGenerator[rtc.AudioFrame, None]:
            nonlocal first_frame
            cfg = get_voice_config(buffered_character, buffered_emotion)
            segment_tts = _make_tts(voice=cfg.voice, speaking_rate=cfg.speaking_rate)
            async with segment_tts.synthesize(chunk) as stream:
                async for ev in stream:
                    if first_frame:
                        self._turn_timer.mark("tts_first_byte")
                        first_frame = False
                    yield ev.frame

        # Transcript accumulation — collect full text per character before logging
        transcript_text = ""

        def flush_transcript() -> None:
            nonlocal transcript_text
            clean = transcript_text.strip()
            if clean and self._transcript:
                self._fire_and_forget(self._transcript.log_dm(buffered_character, buffered_emotion, clean))
            transcript_text = ""

        async def flush_buffer() -> AsyncGenerator[rtc.AudioFrame, None]:
            nonlocal buffered_text
            clean = buffered_text.strip()
            buffered_text = ""
            if not clean or not re.sub(r"[^\w]", "", clean):
                return

            parts = _PAUSE_PATTERN.split(clean)
            for part in parts:
                pause = _PAUSE_DURATIONS.get(part)
                if pause is not None:
                    yield _silence(pause)
                elif part.strip() and re.sub(r"[^\w]", "", part):
                    async for frame in synthesize_chunk(part.strip()):
                        yield frame

        async for segment in parse_dialogue_stream(text):
            if segment.character != buffered_character or segment.emotion != buffered_emotion:
                async for frame in flush_buffer():
                    yield frame
                flush_transcript()
                buffered_character = segment.character
                buffered_emotion = segment.emotion

            transcript_text += segment.text
            buffered_text += segment.text

            if re.search(r'[.!?][""\u201d]?\s*$', buffered_text):
                async for frame in flush_buffer():
                    yield frame
                yield _silence(1.0)

        async for frame in flush_buffer():
            yield frame
        flush_transcript()

        self._turn_timer.finish()
        self._affect_analyzer.record_tts_end()


_PAUSE_PATTERN = re.compile(r"(\.{2,}|…|—|–)")

_PAUSE_DURATIONS: dict[str, float] = {
    "...": 0.6,
    "…": 0.6,
    "—": 0.3,
    "–": 0.3,
}

TTS_SAMPLE_RATE = 24000
TTS_NUM_CHANNELS = 1


def _silence(seconds: float) -> rtc.AudioFrame:
    samples = int(TTS_SAMPLE_RATE * seconds)
    return rtc.AudioFrame(
        data=b"\x00\x00" * samples * TTS_NUM_CHANNELS,
        sample_rate=TTS_SAMPLE_RATE,
        num_channels=TTS_NUM_CHANNELS,
        samples_per_channel=samples,
    )


def _make_tts(voice: str = "", speaking_rate: float = 1.0) -> inworld.TTS:
    kwargs: dict[str, Any] = {"speaking_rate": speaking_rate}
    if voice:
        kwargs["voice"] = voice
    return inworld.TTS(**kwargs)


server = AgentServer()


def _extract_player_id(ctx: agents.JobContext) -> str:
    """Extract player_id from dispatch metadata, falling back to 'player_1' for dev."""
    metadata = ctx.job.metadata if ctx.job else None
    if metadata:
        try:
            data = json.loads(metadata)
            pid = data.get("player_id")
            if isinstance(pid, str) and pid:
                return pid
        except (json.JSONDecodeError, TypeError):
            pass
    logger.warning("No player_id in dispatch metadata — falling back to 'player_1'")
    return "player_1"


@server.rtc_session(agent_name="divineruin-dm")
async def dm_session(ctx: agents.JobContext) -> None:
    player_id = _extract_player_id(ctx)
    userdata = SessionData(
        player_id=player_id,
        location_id=START_LOCATION,
        room=ctx.room,
    )

    # Load companion if player has met Kael
    try:
        companion_met = await db.get_player_flag(player_id, "companion_met")
        if companion_met:
            userdata.companion = CompanionState(
                id="companion_kael",
                name="Kael",
                last_speech_time=time.time(),
            )
            logger.info("Companion Kael loaded for returning player")
    except Exception:
        logger.warning("Failed to check companion_met flag", exc_info=True)

    session = AgentSession(
        stt=deepgram.STT(model="nova-3", language="en"),
        llm=anthropic.LLM(
            model="claude-haiku-4-5-20251001",
            temperature=0.8,
        ),
        tts=_make_tts(),
        vad=silero.VAD.load(min_silence_duration=0.5),
        turn_detection=MultilingualModel(),
        allow_interruptions=True,
        min_endpointing_delay=0.5,
        userdata=userdata,
    )

    @session.on("agent_state_changed")
    def _on_agent_state(ev):
        if ev.old_state == "speaking" and ev.new_state == "listening":
            userdata.last_agent_speech_end = time.time()

    await session.start(
        room=ctx.room,
        agent=DungeonMasterAgent(),
    )

    await session.generate_reply(
        instructions=(
            "Call enter_location with 'accord_guild_hall' to get the full scene context. "
            "Do NOT tell the player you are looking anything up or setting a scene. "
            "Do NOT use meta-language like 'setting the scene' or 'let me describe'. "
            "Just BE the narrator — start directly with what the player experiences. "
            "The player pushes open the heavy door of the guild hall. It's evening. "
            "Describe the atmosphere. Then Guildmaster Torin notices them and speaks, "
            "gruff and direct. Use the [GUILDMASTER_TORIN, stern] tag for his dialogue. "
            "End with something that invites the player to respond."
        ),
    )


if __name__ == "__main__":
    validate_env()
    import atexit

    def _cleanup_db() -> None:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(db.close_all())  # noqa: RUF006
            else:
                loop.run_until_complete(db.close_all())
        except Exception:
            pass

    atexit.register(_cleanup_db)
    agents.cli.run_app(server)
