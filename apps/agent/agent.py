import asyncio
import json
import logging
import os
import re
import time

from livekit import agents, rtc
from livekit.agents import AgentServer, AgentSession
from livekit.plugins import anthropic, deepgram, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

import db
from base_agent import _make_tts
from city_agent import CityAgent
from session_data import CompanionState, CreationState, SessionData
from voices import VOICES

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


def validate_env() -> None:
    missing = [v for v in REQUIRED_ENV_VARS if not os.getenv(v)]
    empty_voices = [k for k, v in VOICES.items() if not v]
    if empty_voices:
        logger.warning("Voice IDs not set for: %s", ", ".join(empty_voices))
    if missing:
        raise OSError(f"Missing required environment variables: {', '.join(missing)}")


START_LOCATION = "accord_guild_hall"


server = AgentServer()


def _extract_player_id(ctx: agents.JobContext) -> str:
    """Extract player_id from dispatch metadata.

    Falls back to 'player_1' in development; raises ValueError in production.
    """
    metadata = ctx.job.metadata if ctx.job else None
    if metadata:
        try:
            data = json.loads(metadata)
            pid = data.get("player_id")
            if isinstance(pid, str) and pid:
                if not re.match(r"^[a-zA-Z0-9_-]+$", pid) or len(pid) > 64:
                    logger.warning("Invalid player_id in metadata: %r", pid)
                else:
                    return pid
        except (json.JSONDecodeError, TypeError):
            pass
    env = os.getenv("AGENT_ENV", "development")
    if env == "production":
        raise ValueError("Missing or invalid player_id in dispatch metadata (production)")
    logger.warning("No player_id in dispatch metadata — falling back to 'player_1' (env=%s)", env)
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
            turn_handling={
                "turn_detection": MultilingualModel(),
                "endpointing": {"min_delay": 0.5},
                "interruption": {"enabled": True},
            },
            userdata=userdata,
        )

        @session.on("agent_state_changed")
        def _on_agent_state(ev):
            if ev.old_state == "speaking" and ev.new_state == "listening":
                userdata.last_agent_speech_end = time.time()

        return session

    if needs_creation:
        # --- Character creation mode ---
        # PrologueAgent plays audio, hands off to CreationAgent,
        # which guides creation and hands off to CityAgent via finalize_character.
        from prologue_agent import PrologueAgent

        userdata = SessionData(
            player_id=player_id,
            location_id="",
            room=ctx.room,
            creation_state=CreationState(),
        )
        session = _make_agent_session("claude-sonnet-4-20250514", userdata)
        await session.start(room=ctx.room, agent=PrologueAgent())
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
        city_agent = CityAgent(initial_location=location_id)

        await session.start(
            room=ctx.room,
            agent=city_agent,
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
            if city_agent._background:
                city_agent._background.pause()
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
            if city_agent._background:
                city_agent._background.resume()
            city_agent._fire_and_forget(
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
