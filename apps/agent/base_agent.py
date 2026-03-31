"""BaseGameAgent — shared voice pipeline and lifecycle infrastructure for all game agents."""

import asyncio
import logging
import re
from collections.abc import AsyncGenerator, AsyncIterable
from typing import Any

from livekit import agents, rtc
from livekit.agents import Agent, ModelSettings, stt
from livekit.agents.stt import SpeechEventType
from livekit.plugins import inworld

from affect_analyzer import PlayerAffectAnalyzer
from dialogue_parser import parse_dialogue_stream
from latency import TurnTimer
from session_data import SessionData
from transcript import TranscriptLogger
from tts_pauses import PAUSE_DURATIONS as _PAUSE_DURATIONS
from tts_pauses import PAUSE_PATTERN as _PAUSE_PATTERN
from tts_pauses import SENTENCE_END_PAUSE
from voices import apply_markup, get_voice_config

logger = logging.getLogger("divineruin.base")

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


class BaseGameAgent(Agent):
    """Shared base for all Divine Ruin game agents.

    Provides the voice pipeline (TTS with multi-character dialogue parsing,
    STT with affect analysis, LLM with retry logic), background task management,
    and lifecycle hooks for affect analyzer and transcript logger.

    Subclasses add agent-specific behavior: BackgroundProcess, hot context,
    session summary (DungeonMasterAgent), or combat-specific logic (CombatAgent).
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

        self._turn_timer = TurnTimer()
        self._affect_analyzer = PlayerAffectAnalyzer()
        self._transcript: TranscriptLogger | None = None
        self._bg_tasks: set[asyncio.Task[None]] = set()

    def _fire_and_forget(self, coro: Any) -> None:
        task = asyncio.create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._on_bg_task_done)

    def _on_bg_task_done(self, task: asyncio.Task[None]) -> None:
        self._bg_tasks.discard(task)
        if not task.cancelled() and task.exception():
            logger.error("Background task failed", exc_info=task.exception())

    async def on_enter(self) -> None:
        logger.info("%s entered session", type(self).__name__)
        self._affect_analyzer.start()
        sd: SessionData = self.session.userdata
        self._transcript = TranscriptLogger(sd.room, sd.event_bus)

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
                    return
                if attempt < max_retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
                else:
                    yield "The threads of fate tangle for a moment... What were you saying?"

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
