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
import db_content_queries
import db_queries
from base_agent import _make_tts
from region_types import REGION_CITY
from session_data import CreationState, SessionData
from token_tracker import TokenTracker
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


def _build_reconnect_instruction(sd: SessionData) -> str:
    """Build a context-rich reconnection greeting instruction."""
    parts = ["The player reconnected after a brief drop."]
    loc_name = sd.cached_location_name or sd.location_id
    if loc_name:
        parts.append(f"They are at {loc_name}.")
    if sd.companion and sd.companion.is_present:
        parts.append(f"{sd.companion.name} is with them.")
    if sd.combat_state:
        parts.append("They are in combat.")
    parts.append("Welcome them back naturally in one short sentence and remind them where they were.")
    return " ".join(parts)


RECONNECT_GRACE_S = 120  # 2 minutes


def _setup_reconnection(
    room: rtc.Room,
    session: AgentSession,
    userdata: SessionData,
    agent,
) -> None:
    """Register disconnect/reconnect handlers for any agent type."""
    reconnect_task: asyncio.Task | None = None
    player_id = userdata.player_id

    @room.on("participant_disconnected")
    def _on_disconnect(participant: rtc.RemoteParticipant):
        nonlocal reconnect_task
        if participant.identity != player_id:
            return
        userdata.player_disconnected = True
        userdata.disconnect_time = time.time()
        bg = getattr(agent, "_background", None)
        if bg:
            bg.pause()
        reconnect_task = asyncio.create_task(_grace_timeout())

    @room.on("participant_connected")
    def _on_reconnect(participant: rtc.RemoteParticipant):
        nonlocal reconnect_task
        if participant.identity != player_id or not userdata.player_disconnected:
            return
        userdata.player_disconnected = False
        if reconnect_task and not reconnect_task.done():
            reconnect_task.cancel()
            reconnect_task = None
        bg = getattr(agent, "_background", None)
        if bg:
            bg.resume()
        fire = getattr(agent, "_fire_and_forget", None)
        reconnect_reply = session.generate_reply(instructions=_build_reconnect_instruction(userdata))
        if fire:
            fire(reconnect_reply)
        else:
            _handle = reconnect_reply  # SpeechHandle is already started

    async def _grace_timeout():
        await asyncio.sleep(RECONNECT_GRACE_S)
        logger.info("Reconnect grace period expired for %s", player_id)
        await session.aclose()


@server.rtc_session(agent_name="divineruin-dm")
async def dm_session(ctx: agents.JobContext) -> None:
    player_id = _extract_player_id(ctx)

    # Load the archetype chassis once per agent process. award_xp / update_quest
    # call calculate_max_hp -> get_archetype_chassis, which needs the chassis
    # populated (M2.1 folded the old module-level HP/resource constants into the
    # DB-loaded SSOT). The async worker loads it separately at its own startup.
    from archetypes import is_loaded, load_archetypes

    if not is_loaded():
        await load_archetypes()

    # Load the archetype abilities once per agent process (M2.2). The DM voices
    # ability activations via request_ability_activation, which reads this map.
    from abilities import is_loaded as abilities_is_loaded
    from abilities import load_abilities

    if not abilities_is_loaded():
        await load_abilities()

    # Load the archetype milestones once per agent process (M2.3). The DM voices
    # milestone progression via resolve_milestone, which reads this map.
    from milestones import is_loaded as milestones_is_loaded
    from milestones import load_milestones

    if not milestones_is_loaded():
        await load_milestones()

    # Load the elective spell catalog once per agent process (M8). learn(spell,id)
    # and spell preparation read this map; caster core spells stay abilities.
    from spells import is_loaded as spells_is_loaded
    from spells import load_spells

    if not spells_is_loaded():
        await load_spells()

    # Load the mentor variant catalog once per agent process (M9). Activation
    # applies an unlocked variant's cost/effect/narration override, which reads
    # this map; the catalog keys variants to base martial elective techniques.
    from mentor_variants import is_loaded as mentor_variants_is_loaded
    from mentor_variants import load_mentor_variants

    if not mentor_variants_is_loaded():
        await load_mentor_variants()

    # Load the role archetype catalog once per agent process (M6.1). NPC stat-block
    # templates (services, combat stats, disposition baselines) consumed by
    # create_npc_from_archetype and settlement generation (M6.2).
    from role_archetypes import is_loaded as role_archetypes_is_loaded
    from role_archetypes import load_role_archetypes

    if not role_archetypes_is_loaded():
        await load_role_archetypes()

    # Settlement population templates (content/settlement_templates.json) — per-tier role
    # counts + personality modifiers consumed by settlement NPC generation (M6.2, story-003).
    # Guarded so the seed_settlement_templates test fixture skips the DB fetch.
    from settlement_templates import is_loaded as settlement_templates_is_loaded
    from settlement_templates import load_settlement_templates

    if not settlement_templates_is_loaded():
        await load_settlement_templates()

    # Authored NPC catalog (content/npcs.json) for synchronous narration consumers —
    # activity_templates derives crafting/training personas from it (story-004 shim
    # consolidation). Guarded so the seed_npcs test fixture skips the DB fetch.
    from npcs import is_loaded as npcs_is_loaded
    from npcs import load_npcs

    if not npcs_is_loaded():
        await load_npcs()

    # Companion catalog (content/companions.json) — typed combat profiles + scaling_rules for
    # the 4 companions. Guarded so the seed_companion_profiles test fixture skips the DB fetch.
    from companion_profiles import is_loaded as companion_profiles_is_loaded
    from companion_profiles import load_companion_profiles

    if not companion_profiles_is_loaded():
        await load_companion_profiles()

    # Determine session type: new player (creation) vs returning
    player = None
    last_summary = None
    try:
        player, last_summary = await asyncio.gather(
            db_queries.get_player(player_id),
            db_queries.get_last_session_summary(player_id),
        )
    except Exception:
        logger.warning("Failed to load player/session data", exc_info=True)

    needs_creation = player is None or not player.get("name")

    def _make_agent_session(model: str, userdata: SessionData) -> AgentSession:
        session = AgentSession(
            stt=deepgram.STT(model="nova-3", language="en"),
            llm=anthropic.LLM(model=model, temperature=0.8, caching="ephemeral"),
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

        tracker = TokenTracker()
        session.on("metrics_collected", tracker.on_metrics)

        return session

    if needs_creation:
        # --- Character creation mode ---
        # PrologueAgent plays audio, hands off to CreationAgent,
        # which guides creation and hands off to the exploration agent via finalize_character.
        from prologue_agent import PrologueAgent

        userdata = SessionData(
            player_id=player_id,
            location_id="",
            room=ctx.room,
            creation_state=CreationState(),
        )
        session = _make_agent_session("claude-sonnet-4-20250514", userdata)
        prologue_agent = PrologueAgent()
        await session.start(room=ctx.room, agent=prologue_agent)
        _setup_reconnection(ctx.room, session, userdata, prologue_agent)
    else:
        # --- Existing gameplay flow ---
        assert player is not None  # guaranteed by needs_creation check
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

        if player.get("flags", {}).get("companion_met"):
            from companion_relationship_queries import hydrate_companion_state

            # Fresh session: hydrate persisted relationship state + increment session_count once
            # (M6.4 / story-003). Reconnects reuse the in-memory CompanionState, so this runs
            # exactly once per session.
            companion = await hydrate_companion_state(player_id, "companion_kael", "Kael")
            companion.last_speech_time = time.time()
            userdata.companion = companion
            logger.info("Companion Kael loaded for returning player")

        # Check for mid-onboarding reconnection
        onboarding_beat = player.get("flags", {}).get("onboarding_beat")
        if isinstance(onboarding_beat, int):
            from onboarding_agent import OnboardingAgent

            userdata.onboarding_beat = onboarding_beat
            session = _make_agent_session("claude-haiku-4-5-20251001", userdata)
            onboarding_agent = OnboardingAgent(onboarding_beat=onboarding_beat)
            await session.start(room=ctx.room, agent=onboarding_agent)
            _setup_reconnection(ctx.room, session, userdata, onboarding_agent)
            return

        # Dispatch correct gameplay agent based on location's region_type
        from gameplay_agent import create_gameplay_agent

        location_data = await db_content_queries.get_location(location_id)
        region_type = location_data.get("region_type", REGION_CITY) if location_data else REGION_CITY
        gameplay_agent = create_gameplay_agent(region_type, location_id, companion=userdata.companion)

        session = _make_agent_session("claude-haiku-4-5-20251001", userdata)

        await session.start(
            room=ctx.room,
            agent=gameplay_agent,
        )

        _setup_reconnection(ctx.room, session, userdata, gameplay_agent)

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
