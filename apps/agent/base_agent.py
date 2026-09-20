"""BaseGameAgent — shared voice pipeline and lifecycle infrastructure for all game agents."""

import asyncio
import logging
import re
from collections.abc import AsyncGenerator, AsyncIterable
from typing import Any

from livekit import agents, rtc
from livekit.agents import Agent, ModelSettings, stt
from livekit.agents.llm import ChatChunk
from livekit.agents.stt import SpeechEventType
from livekit.plugins import inworld

from affect_analyzer import PlayerAffectAnalyzer
from dialogue_parser import parse_dialogue_stream
from gameplay_llm import is_luna_pilot
from latency import TurnTimer
from session_data import SessionData
from task_logging import log_task_failure
from transcript import TranscriptLogger
from tts_pauses import PAUSE_DURATIONS as _PAUSE_DURATIONS
from tts_pauses import PAUSE_PATTERN as _PAUSE_PATTERN
from tts_pauses import SENTENCE_END_PAUSE
from voices import INWORLD_MODEL, apply_markup, get_voice_config

logger = logging.getLogger("divineruin.base")

TTS_SAMPLE_RATE = 24000
TTS_NUM_CHANNELS = 1
UNRESOLVED_TURN_MESSAGE = "The threads of fate tangle for a moment... What were you saying?"
PLAYER_INTERRUPT_SOURCES = {"audio_activity", "user_turn"}


def _player_interrupted(agent: Agent) -> bool:
    try:
        speech = agent.session.current_speech
    except RuntimeError:
        return False
    # `_interrupt_source` is the one read livekit exposes no public accessor for.
    return bool(speech and speech.interrupted and speech._interrupt_source in PLAYER_INTERRUPT_SOURCES)


def _silence(seconds: float) -> rtc.AudioFrame:
    samples = int(TTS_SAMPLE_RATE * seconds)
    return rtc.AudioFrame(
        data=b"\x00\x00" * samples * TTS_NUM_CHANNELS,
        sample_rate=TTS_SAMPLE_RATE,
        num_channels=TTS_NUM_CHANNELS,
        samples_per_channel=samples,
    )


def _make_tts(voice: str = "", speaking_rate: float = 1.0) -> inworld.TTS:
    kwargs: dict[str, Any] = {
        "model": INWORLD_MODEL,
        "speaking_rate": speaking_rate,
    }
    if voice:
        kwargs["voice"] = voice
    return inworld.TTS(**kwargs)


class ReportingEntry(Agent):
    """Base for every game agent: `on_enter` REPORTS whatever its entry body raises.

    LiveKit does log an escaping `on_enter` (`agent_activity._traceable_on_enter` carries
    `utils.log_exceptions`), but under the `livekit.agents` logger and against the vendor's
    own function name — so the line that says WHICH agent entered half-built is not there,
    and it is outside the `divineruin.*` tree. Agents put their entry body in `_enter` and
    never override `on_enter`, so an agent gets the named report by existing rather than by
    remembering to ask for it.
    """

    async def on_enter(self) -> None:
        try:
            await self._enter()
        except Exception as exc:
            logger.error("%s entry failed", type(self).__name__, exc_info=exc)

    async def _enter(self) -> None:
        """This agent's entry body. Override this, not `on_enter`."""


class BaseGameAgent(ReportingEntry):
    """Shared base for all Divine Ruin game agents.

    Provides the voice pipeline (TTS with multi-character dialogue parsing,
    STT with affect analysis, LLM with retry logic), background task management,
    and lifecycle hooks for affect analyzer and transcript logger.

    Subclasses add agent-specific behavior: hot context and the session's BackgroundProcess
    (ExplorationAgent), or combat-specific logic (CombatAgent).
    """

    def __init__(
        self,
        instructions: str,
        tools: list | None = None,
        chat_ctx: Any = None,
    ) -> None:
        init_kwargs: dict[str, Any] = {
            "instructions": instructions,
            "tools": tools or [],
        }
        if chat_ctx is not None:
            init_kwargs["chat_ctx"] = chat_ctx
        super().__init__(**init_kwargs)

        self._static_instructions = instructions
        self._turn_timer = TurnTimer()
        self._affect_analyzer = PlayerAffectAnalyzer()
        self._transcript: TranscriptLogger | None = None
        self._bg_tasks: set[asyncio.Task[None]] = set()

    def static_prompt(self, sd: SessionData) -> str:
        """This agent's own static prompt half — what the session's warm layer is appended to.

        The BackgroundProcess is session-scoped and injects into whichever agent holds the
        floor, so the static half has to come from that agent: composing the exploration
        prompt onto a CombatAgent would replace COMBAT_SYSTEM_PROMPT mid-fight.
        """
        return self._static_instructions

    def _fire_and_forget(self, coro: Any) -> None:
        task = asyncio.create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._on_bg_task_done)

    def _on_bg_task_done(self, task: asyncio.Task[None]) -> None:
        self._bg_tasks.discard(task)
        log_task_failure(task, logger, "Background task failed")

    async def _enter(self) -> None:
        logger.info("%s entered session", type(self).__name__)
        self._affect_analyzer.start()
        sd: SessionData = self.session.userdata
        # One transcript file for the whole SESSION: the first agent to enter mints the path
        # and every agent after it appends to the same file. TranscriptLogger mints a fresh
        # timestamped path when given none, so per-agent handles left the end-of-session recap
        # reading only the last agent's half of the conversation.
        self._transcript = TranscriptLogger(sd.room, sd.event_bus, log_path=sd.transcript_path)
        sd.transcript_path = self._transcript.log_path

    async def on_exit(self) -> None:
        logger.info("%s exiting session", type(self).__name__)

        # Cancel in-flight background tasks
        for task in list(self._bg_tasks):
            task.cancel()
        if self._bg_tasks:
            await asyncio.gather(*self._bg_tasks, return_exceptions=True)

        try:
            await self._affect_analyzer.stop()
        except Exception:
            logger.exception("Failed to stop affect analyzer")

        if self._transcript:
            self._transcript.close()

    async def stt_node(
        self,
        audio: AsyncIterable[rtc.AudioFrame],
        model_settings: ModelSettings,
    ) -> AsyncGenerator[stt.SpeechEvent | str, None]:
        """Override stt_node to fork STT events to the affect analyzer."""
        async for event in Agent.default.stt_node(self, audio, model_settings):
            if isinstance(event, stt.SpeechEvent) and event.type == SpeechEventType.FINAL_TRANSCRIPT:
                self._affect_analyzer.enqueue_event(event)
                if self._transcript and event.alternatives:
                    self._fire_and_forget(self._transcript.log_player(event.alternatives[0].text))
            yield event

    async def llm_node(
        self,
        chat_ctx: agents.llm.ChatContext,
        tools: list,
        model_settings: ModelSettings,
    ) -> AsyncGenerator:
        try:
            selected_llm = self.session.llm
        except RuntimeError:
            selected_llm = None
        if is_luna_pilot(selected_llm):
            async for chunk in self._atomic_llm_node(chat_ctx, tools, model_settings):
                yield chunk
            return

        max_retries = 2
        for attempt in range(max_retries + 1):
            yielded_any = False
            try:
                async for chunk in Agent.default.llm_node(self, chat_ctx, tools, model_settings):
                    yielded_any = True
                    # The ONLY tap that sees cache_creation_tokens: livekit drops it building
                    # LLMMetrics, so `metrics_collected` cannot report a cache write.
                    usage = getattr(chunk, "usage", None)
                    if usage is not None:
                        self.session.userdata.tokens.on_usage(usage)
                    yield chunk
                return
            except Exception as e:
                logger.error("LLM error (attempt %d/%d): %s", attempt + 1, max_retries + 1, e)
                if yielded_any:
                    return
                if attempt < max_retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
                else:
                    yield UNRESOLVED_TURN_MESSAGE

    async def _atomic_llm_node(
        self,
        chat_ctx: agents.llm.ChatContext,
        tools: list,
        model_settings: ModelSettings,
    ) -> AsyncGenerator:
        """Release a turn only once the provider stream reaches terminal success.

        livekit 1.8.2 forwards each generated call into `function_ch` as the chunk arrives
        (`voice/generation.py`) and `agent_activity` may execute it before the stream ends, so
        a provider error after a complete call chunk would leave a half-applied mutation.
        Buffering is the price: story-215 measures it against the 1500ms first-audio budget.
        """
        buffered = []
        has_output = False
        has_terminal_usage = False
        try:
            async for chunk in Agent.default.llm_node(self, chat_ctx, tools, model_settings):
                usage = getattr(chunk, "usage", None)
                if usage is not None:
                    self.session.userdata.tokens.on_usage(usage)
                    has_terminal_usage = True
                if isinstance(chunk, str):
                    has_output = has_output or bool(chunk)
                elif isinstance(chunk, ChatChunk):
                    has_output = has_output or chunk.has_response()
                buffered.append(chunk)
        except asyncio.CancelledError:
            if _player_interrupted(self):
                return
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                task.uncancel()
            logger.error("Luna gameplay turn cancelled before terminal success")
            yield UNRESOLVED_TURN_MESSAGE
            return
        except Exception as exc:
            logger.error("Luna gameplay turn failed before terminal success: %s", exc)
            yield UNRESOLVED_TURN_MESSAGE
            return

        if not has_output or not has_terminal_usage:
            logger.error(
                "Luna gameplay turn ended without terminal success (output=%s, usage=%s)",
                has_output,
                has_terminal_usage,
            )
            yield UNRESOLVED_TURN_MESSAGE
            return

        for chunk in buffered:
            yield chunk

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
            marked_up = apply_markup(chunk, cfg.inworld_markup)
            async with cached_tts.synthesize(marked_up) as stream:
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
                yield _silence(SENTENCE_END_PAUSE)

        async for frame in flush_buffer():
            yield frame
        flush_transcript()

        self._turn_timer.finish()
        self._affect_analyzer.record_tts_end()
