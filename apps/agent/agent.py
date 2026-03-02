import logging
import os
from collections.abc import AsyncIterable, AsyncGenerator
from typing import Any

from livekit import rtc, agents
from livekit.agents import AgentServer, AgentSession, Agent, ModelSettings
from livekit.plugins import silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from livekit.plugins import anthropic, deepgram, inworld

from prompts import SYSTEM_PROMPT
from voices import get_voice_config, VOICES
from dialogue_parser import parse_dialogue_stream
from latency import TurnTimer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("divineruin.dm")

REQUIRED_ENV_VARS = [
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "ANTHROPIC_API_KEY",
    "DEEPGRAM_API_KEY",
    "INWORLD_API_KEY",
]


def validate_env() -> None:
    missing = [v for v in REQUIRED_ENV_VARS if not os.getenv(v)]
    empty_voices = [k for k, v in VOICES.items() if not v]
    if empty_voices:
        logger.warning("Voice IDs not set for: %s", ", ".join(empty_voices))
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}"
        )


class DungeonMasterAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=SYSTEM_PROMPT)
        self._turn_timer = TurnTimer()

    def on_enter(self) -> None:
        logger.info("DM agent entered session")

    def on_user_turn_completed(self, turn_ctx: Any) -> None:
        self._turn_timer.start()
        self._turn_timer.mark("user_turn_end")

    async def tts_node(
        self, text: AsyncIterable[str], model_settings: ModelSettings
    ) -> AsyncGenerator[rtc.AudioFrame, None]:
        self._turn_timer.mark("tts_start")
        first_frame = True

        async for segment in parse_dialogue_stream(text):
            cfg = get_voice_config(segment.character, segment.emotion)
            segment_tts = _make_tts(voice=cfg.voice, speaking_rate=cfg.speaking_rate)

            async with segment_tts.synthesize(segment.text) as stream:
                async for ev in stream:
                    if first_frame:
                        self._turn_timer.mark("tts_first_byte")
                        first_frame = False
                    yield ev.frame

        self._turn_timer.finish()


def _make_tts(voice: str = "", speaking_rate: float = 1.0) -> inworld.TTS:
    kwargs: dict[str, Any] = {"speaking_rate": speaking_rate}
    if voice:
        kwargs["voice"] = voice
    return inworld.TTS(**kwargs)


server = AgentServer()


@server.rtc_session(agent_name="divineruin-dm")
async def dm_session(ctx: agents.JobContext) -> None:
    session = AgentSession(
        stt=deepgram.STT(model="nova-3", language="en"),
        llm=anthropic.LLM(
            model="claude-haiku-4-5-20251001",
            temperature=0.8,
        ),
        tts=_make_tts(),
        vad=silero.VAD.load(silence_duration_ms=500),
        turn_detection=MultilingualModel(),
        allow_interruptions=True,
        min_endpointing_delay=0.5,
    )

    await session.start(
        room=ctx.room,
        agent=DungeonMasterAgent(),
    )

    await session.generate_reply(
        instructions="Greet the player as they enter the world. Set the scene briefly: they stand at the edge of a ruined village at dusk, wind carrying the scent of ash. Two to three sentences, atmospheric, inviting them to explore.",
    )


if __name__ == "__main__":
    validate_env()
    agents.cli.run_app(server)
