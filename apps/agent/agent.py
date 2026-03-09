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
from prompts import build_system_prompt, format_affect_context
from rules_engine import hp_threshold_status
from session_data import CompanionState, CreationState, SessionData
from session_summary import generate_session_summary
from tools import (
    add_to_inventory,
    award_divine_favor,
    award_xp,
    discover_hidden_element,
    end_combat,
    end_session,
    enter_location,
    move_player,
    play_sound,
    query_inventory,
    query_location,
    query_lore,
    query_npc,
    record_story_moment,
    remove_from_inventory,
    request_attack,
    request_death_save,
    request_saving_throw,
    request_skill_check,
    resolve_enemy_turn,
    roll_dice,
    set_music_state,
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
    "INTERNAL_SECRET",
]

WORLD_TOOLS = [enter_location, query_location, query_npc, query_lore, query_inventory, discover_hidden_element]
MECHANICS_TOOLS = [request_skill_check, request_attack, request_saving_throw, roll_dice, play_sound, set_music_state]
MUTATION_TOOLS = [
    move_player,
    add_to_inventory,
    remove_from_inventory,
    update_quest,
    award_xp,
    award_divine_favor,
    update_npc_disposition,
    record_story_moment,
    end_session,
]
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
    def __init__(
        self,
        initial_location: str = START_LOCATION,
        instructions: str | None = None,
        tools: list | None = None,
        creation_mode: bool = False,
    ) -> None:
        super().__init__(
            instructions=instructions or build_system_prompt(initial_location),
            tools=tools or ALL_TOOLS,
        )
        self._creation_mode = creation_mode
        self._turn_timer = TurnTimer()
        self._background: BackgroundProcess | None = None
        self._affect_analyzer = PlayerAffectAnalyzer()
        self._transcript: TranscriptLogger | None = None
        self._bg_tasks: set[asyncio.Task[None]] = set()
        self._session_start_time: float = time.time()
        self._close_scheduled: bool = False

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
        logger.info("DM agent entered session (creation_mode=%s)", self._creation_mode)
        self._session_start_time = time.time()
        self._affect_analyzer.start()
        sd: SessionData = self.session.userdata
        self._transcript = TranscriptLogger(sd.room, sd.event_bus)

        if not self._creation_mode:
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

        transcript_path = self._transcript.log_path if self._transcript else None
        summary_payload = await generate_session_summary(sd, transcript_path, self._session_start_time)

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

        # Skip hot context injection during creation — no location/quest/NPC data yet
        if not self._creation_mode:
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

    async def llm_node(
        self,
        chat_ctx: agents.llm.ChatContext,
        tools: list,
        model_settings: ModelSettings,
    ) -> AsyncGenerator:
        max_retries = 2
        for attempt in range(max_retries + 1):
            yielded_any = False
            try:
                async for chunk in Agent.default.llm_node(self, chat_ctx, tools, model_settings):
                    yielded_any = True
                    yield chunk
                return
            except Exception as e:
                logger.error("LLM error (attempt %d/%d): %s", attempt + 1, max_retries + 1, e)
                if yielded_any:
                    # Already sent partial output — can't retry cleanly
                    return
                if attempt < max_retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
                else:
                    yield "The threads of fate tangle for a moment... What were you saying?"

    def _build_hot_context(self, sd: SessionData) -> str:
        """Build hot context from in-memory SessionData only — zero I/O.

        All data is kept current by the background process warm layer rebuild.
        """
        parts: list[str] = []

        # Current location + time (cached by background process)
        loc_name = sd.cached_location_name or sd.location_id
        parts.append(f"[Context: {loc_name}, {sd.world_time}]")

        # Combat state (in-memory)
        if sd.combat_state is not None:
            cs = sd.combat_state
            combatants = []
            for pid in cs.initiative_order:
                p = cs.get_participant(pid)
                if p is not None:
                    status = hp_threshold_status(p.hp_current, p.hp_max)
                    combatants.append(f"{p.name}({status})")
            parts.append(f"[COMBAT Round {cs.round_number}: {', '.join(combatants)}]")

        # Active quest objectives (cached by background process)
        if sd.cached_quest_summaries:
            parts.append("[Quests: " + "; ".join(sd.cached_quest_summaries) + "]")

        # Recent events (in-memory deque)
        if sd.recent_events:
            recent = list(sd.recent_events)[-3:]
            parts.append("[Recent: " + "; ".join(recent) + "]")

        # NPCs nearby (cached by background process)
        if sd.cached_npc_names:
            parts.append("[NPCs nearby: " + ", ".join(sd.cached_npc_names) + "]")

        return " ".join(parts)

    async def tts_node(
        self, text: AsyncIterable[str], model_settings: ModelSettings
    ) -> AsyncGenerator[rtc.AudioFrame, None]:
        self._turn_timer.mark("tts_start")
        first_frame = True

        buffered_text = ""
        buffered_character = ""
        buffered_emotion = ""

        # Cache TTS instance to reuse when voice config hasn't changed
        cached_tts: inworld.TTS | None = None
        cached_voice_key: tuple[str, float] = ("", 1.0)

        async def synthesize_chunk(chunk: str) -> AsyncGenerator[rtc.AudioFrame, None]:
            nonlocal first_frame, cached_tts, cached_voice_key
            cfg = get_voice_config(buffered_character, buffered_emotion)
            voice_key = (cfg.voice, cfg.speaking_rate)
            if cached_tts is None or voice_key != cached_voice_key:
                cached_tts = _make_tts(voice=cfg.voice, speaking_rate=cfg.speaking_rate)
                cached_voice_key = voice_key
            async with cached_tts.synthesize(chunk) as stream:
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
                yield _silence(0.8)

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
                if not re.match(r"^[a-zA-Z0-9_-]+$", pid) or len(pid) > 64:
                    logger.warning("Invalid player_id in metadata: %r — falling back", pid)
                else:
                    return pid
        except (json.JSONDecodeError, TypeError):
            pass
    logger.warning("No player_id in dispatch metadata — falling back to 'player_1'")
    return "player_1"


def _build_recap_instruction(last_summary: dict | None) -> str:
    """Build a recap instruction from the previous session's summary."""
    if not last_summary:
        return ""

    parts: list[str] = []

    summary_text = last_summary.get("summary", "")
    if summary_text:
        parts.append(f"Last session: {summary_text.strip()}")

    key_events = last_summary.get("key_events", [])
    if key_events:
        events_str = "; ".join(key_events[:5])
        parts.append(f"Key events: {events_str}.")

    next_hooks = last_summary.get("next_hooks", [])
    if next_hooks:
        hooks_str = "; ".join(next_hooks[:2])
        parts.append(f"Unresolved threads to weave in: {hooks_str}.")

    decisions = last_summary.get("decisions", [])
    if decisions:
        dec_str = "; ".join(decisions[:3])
        parts.append(f"Player choices that matter: {dec_str}.")

    if not parts:
        return ""

    return " " + " ".join(parts)


@server.rtc_session(agent_name="divineruin-dm")
async def dm_session(ctx: agents.JobContext) -> None:
    player_id = _extract_player_id(ctx)

    # Determine session type: new player (creation) vs returning
    player = None
    last_summary = None
    try:
        player, last_summary = await asyncio.gather(
            db.get_player(player_id),
            db.get_last_session_summary(player_id),
        )
    except Exception:
        logger.warning("Failed to load player/session data", exc_info=True)

    needs_creation = player is None or not player.get("name")

    def _make_agent_session(model: str, userdata: SessionData) -> AgentSession:
        session = AgentSession(
            stt=deepgram.STT(model="nova-3", language="en"),
            llm=anthropic.LLM(model=model, temperature=0.8),
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

        return session

    if needs_creation:
        # --- Character creation mode ---
        from creation_prompts import CREATION_SYSTEM_PROMPT
        from creation_tools import finalize_character, push_creation_cards, set_creation_choice

        userdata = SessionData(
            player_id=player_id,
            location_id="",
            room=ctx.room,
            creation_state=CreationState(),
        )

        creation_tools = [push_creation_cards, set_creation_choice, finalize_character, play_sound, set_music_state]
        session = _make_agent_session("claude-sonnet-4-20250514", userdata)

        await session.start(
            room=ctx.room,
            agent=DungeonMasterAgent(
                instructions=CREATION_SYSTEM_PROMPT,
                tools=creation_tools,
                creation_mode=True,
            ),
        )

        # Play prologue narration, then begin creation
        PROLOGUE_DURATION_S = 80
        await publish_game_event(ctx.room, "play_narration", {"url": "/api/audio/prologue"})
        await asyncio.sleep(PROLOGUE_DURATION_S)

        await session.generate_reply(
            instructions=(
                "The prologue has finished. Begin the Awakening phase. "
                "Call push_creation_cards with category 'race', then ask the player "
                "about their race using the sensory approach from your instructions."
            ),
        )
    else:
        # --- Existing gameplay flow ---
        if last_summary is not None:
            location_id = player.get("location_id", START_LOCATION)
            is_first_session = False
        else:
            location_id = "accord_market_square"
            is_first_session = True

        # Extract patron deity from player data
        divine_favor = player.get("divine_favor", {})
        patron_id = divine_favor.get("patron", "none") if divine_favor else "none"

        userdata = SessionData(
            player_id=player_id,
            location_id=location_id,
            room=ctx.room,
            patron_id=patron_id,
        )

        if player.get("flags", {}).get("companion_met") == "true":
            userdata.companion = CompanionState(
                id="companion_kael",
                name="Kael",
                last_speech_time=time.time(),
            )
            logger.info("Companion Kael loaded for returning player")

        session = _make_agent_session("claude-haiku-4-5-20251001", userdata)
        dm_agent = DungeonMasterAgent(initial_location=location_id)

        await session.start(
            room=ctx.room,
            agent=dm_agent,
        )

        # --- Reconnection handling ---
        RECONNECT_GRACE_S = 120  # 2 minutes
        reconnect_task: asyncio.Task | None = None

        @ctx.room.on("participant_disconnected")
        def _on_disconnect(participant: rtc.RemoteParticipant):
            nonlocal reconnect_task
            if participant.identity != player_id:
                return
            userdata.player_disconnected = True
            userdata.disconnect_time = time.time()
            if dm_agent._background:
                dm_agent._background.pause()
            reconnect_task = asyncio.create_task(_grace_timeout())

        @ctx.room.on("participant_connected")
        def _on_reconnect(participant: rtc.RemoteParticipant):
            nonlocal reconnect_task
            if participant.identity != player_id or not userdata.player_disconnected:
                return
            userdata.player_disconnected = False
            if reconnect_task and not reconnect_task.done():
                reconnect_task.cancel()
                reconnect_task = None
            if dm_agent._background:
                dm_agent._background.resume()
            dm_agent._fire_and_forget(
                session.generate_reply(
                    instructions="The player reconnected after a brief drop. "
                    "Welcome them back naturally in one short sentence and remind them where they were."
                )
            )

        async def _grace_timeout():
            await asyncio.sleep(RECONNECT_GRACE_S)
            logger.info("Reconnect grace period expired for %s", player_id)
            await session.aclose()

        # --- Initial greeting ---
        if is_first_session:
            await session.generate_reply(
                instructions=(
                    f"Call enter_location with '{location_id}' to get the full scene context. "
                    "Do NOT tell the player you are looking anything up or setting a scene. "
                    "Do NOT use meta-language like 'setting the scene' or 'let me describe'. "
                    "Just BE the narrator — start directly with what the player experiences. "
                    "The player steps into the market square of the Accord of Tides. It's evening. "
                    "The market is winding down — vendors packing stalls, the smell of salt and fried fish. "
                    "Describe the atmosphere with one vivid sensory detail. "
                    "End with something that invites the player to look around or explore."
                ),
            )
        else:
            recap = _build_recap_instruction(last_summary)
            await session.generate_reply(
                instructions=(
                    f"Call enter_location with '{location_id}' to get the full scene context. "
                    "Do NOT tell the player you are looking anything up or setting a scene. "
                    "Just BE the narrator — start directly with what the player experiences. "
                    f"The player returns to the world.{recap} "
                    "Describe where they are now with one atmospheric sentence. "
                    "Remind them of their current situation through narration, not summary. "
                    "End with something that invites action."
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
