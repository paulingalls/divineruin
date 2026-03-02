import logging
import os
import re
from collections.abc import AsyncIterable, AsyncGenerator
from typing import Any

from livekit import rtc, agents
from livekit.agents import AgentServer, AgentSession, Agent, ModelSettings
from livekit.plugins import silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from livekit.plugins import anthropic, deepgram, inworld

from prompts import build_system_prompt
from voices import get_voice_config, VOICES
from dialogue_parser import parse_dialogue_stream
from latency import TurnTimer
from session_data import SessionData
from tools import (
    enter_location,
    query_location, query_npc, query_lore, query_inventory,
    request_skill_check, request_attack, request_saving_throw,
    roll_dice, play_sound,
)
import db

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

WORLD_TOOLS = [enter_location, query_location, query_npc, query_lore, query_inventory]
MECHANICS_TOOLS = [request_skill_check, request_attack, request_saving_throw, roll_dice, play_sound]
ALL_TOOLS = WORLD_TOOLS + MECHANICS_TOOLS


def validate_env() -> None:
    missing = [v for v in REQUIRED_ENV_VARS if not os.getenv(v)]
    empty_voices = [k for k, v in VOICES.items() if not v]
    if empty_voices:
        logger.warning("Voice IDs not set for: %s", ", ".join(empty_voices))
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}"
        )


START_LOCATION = "accord_guild_hall"


class DungeonMasterAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=build_system_prompt(START_LOCATION),
            tools=ALL_TOOLS,
        )
        self._turn_timer = TurnTimer()

    async def on_enter(self) -> None:
        logger.info("DM agent entered session")

    async def on_user_turn_completed(
        self, turn_ctx: agents.llm.ChatContext, new_message: agents.llm.ChatMessage
    ) -> None:
        self._turn_timer.start()
        self._turn_timer.mark("user_turn_end")

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

        async def flush_buffer() -> AsyncGenerator[rtc.AudioFrame, None]:
            nonlocal buffered_text
            clean = buffered_text.strip()
            buffered_text = ""
            if not clean or not re.sub(r'[^\w]', '', clean):
                return

            parts = _PAUSE_PATTERN.split(clean)
            for part in parts:
                pause = _PAUSE_DURATIONS.get(part)
                if pause is not None:
                    yield _silence(pause)
                elif part.strip() and re.sub(r'[^\w]', '', part):
                    async for frame in synthesize_chunk(part.strip()):
                        yield frame

        async for segment in parse_dialogue_stream(text):
            if segment.character != buffered_character or segment.emotion != buffered_emotion:
                async for frame in flush_buffer():
                    yield frame
                buffered_character = segment.character
                buffered_emotion = segment.emotion

            buffered_text += segment.text

            if re.search(r'[.!?][""\u201d]?\s*$', buffered_text):
                async for frame in flush_buffer():
                    yield frame
                yield _silence(1.0)

        async for frame in flush_buffer():
            yield frame

        self._turn_timer.finish()


_PAUSE_PATTERN = re.compile(r'(\.{2,}|…|—|–)')

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


@server.rtc_session(agent_name="divineruin-dm")
async def dm_session(ctx: agents.JobContext) -> None:
    userdata = SessionData(
        player_id="player_1",
        location_id=START_LOCATION,
        room=ctx.room,
    )

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
    agents.cli.run_app(server)
