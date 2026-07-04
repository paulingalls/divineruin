"""Room participant lifecycle wiring for the DM session (extracted from agent.py to keep it
focused and under the module-size limit).

Two setup functions register LiveKit ``room.on`` handlers over a live session's participants:

- ``_setup_reconnection`` — disconnect/grace-timeout/reconnect for the PRIMARY player (any agent
  type). A drop pauses the background process and arms a grace timeout; a reconnect within the
  grace window resumes and re-greets.
- ``_setup_party_join`` — the live multi-PC trigger (M18 story-001): a SECOND participant joining
  the room becomes a PartyMember with its own hydrated per-member state.

Both are wired by agent.dm_session; the party-join trigger is wired at gameplay start only.
"""

import asyncio
import logging
import time

from livekit import rtc
from livekit.agents import Agent, AgentSession

import db_mutations_concentration
import db_mutations_resonance
import db_mutations_veil_ward
import db_queries
from caster_state import ConcentrationState, ResonanceTrack, VeilWardState
from party_state import PartyMember
from session_data import SessionData

logger = logging.getLogger("divineruin.dm")

RECONNECT_GRACE_S = 120  # 2 minutes


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


def _setup_reconnection(
    room: rtc.Room,
    session: AgentSession,
    userdata: SessionData,
    agent: Agent,
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


def _setup_party_join(
    room: rtc.Room,
    userdata: SessionData,
    *,
    queries=db_queries,
    resonance_mod=db_mutations_resonance,
    veil_ward_mod=db_mutations_veil_ward,
    concentration_mod=db_mutations_concentration,
) -> None:
    """Register the live participant-join trigger: a SECOND player connecting to the room becomes
    a PartyMember (M18 story-001). This is what makes a >1-member party reachable in prod — every
    session starts solo (1 member) until a real 2nd participant joins.

    Distinct from _setup_reconnection, whose participant_connected handler only handles the PRIMARY
    reconnecting. The sync handler early-returns for the primary identity (reconnection's job) and
    for an already-present member (idempotent — no double-add), else spawns the async DB work as a
    task (a sync LiveKit handler can't await). queries + the read-helper modules are injectable so a
    MagicMock-room unit test can supply AsyncMocks.
    """

    # Retain a strong reference to each spawned join task until it finishes. asyncio only holds a
    # weak reference to the task, so an unreferenced create_task() can be garbage-collected mid-await
    # — silently dropping the member append/hydrate (a fail-silent violation of the fail-loud rule).
    _pending_joins: set[asyncio.Task] = set()

    @room.on("participant_connected")
    def _on_join(participant: rtc.RemoteParticipant) -> None:
        identity = participant.identity
        # The primary (re)connecting is _setup_reconnection's job; an already-present member is a
        # no-op. Both are cheap sync checks BEFORE spawning any DB work.
        if identity == userdata.player_id or userdata.party.contains(identity):
            return
        task = asyncio.create_task(_join_member(identity))
        _pending_joins.add(task)
        task.add_done_callback(_pending_joins.discard)

    async def _join_member(pid: str) -> None:
        row = await queries.get_player(pid)
        if row is None:
            # Boundary/external-input case: a stray participant with no players row must NOT
            # fail-loud the whole room (unlike combat_init's internal-SSOT fail-loud). Log + skip.
            logger.warning("Party-join: no players row for %r; skipping append", pid)
            return
        # Race guard: a second participant_connected for the same pid may have appended during the
        # await above (both events passed the sync contains() check before either task ran).
        if userdata.party.contains(pid):
            return
        member = PartyMember(
            player_id=pid,
            resonance=ResonanceTrack(),
            veil_ward=VeilWardState(),
            concentration=ConcentrationState(),
        )
        userdata.party.members.append(member)  # IN PLACE — never reassign userdata.party (f4f16c93076e)

        # Hydrate ALL FIVE per-member sub-states onto the new member.
        # resonance/veil_ward/concentration: the player_id-parameterized read helpers, applied the
        # same way session_hydration.hydrate_session_state applies them onto the primary.
        res = await resonance_mod.read_player_resonance(pid)
        ward = await veil_ward_mod.read_player_veil_ward(pid)
        conc = await concentration_mod.read_player_concentration(pid)
        member.resonance.current = res["current"]
        member.resonance.flickering_bonus = res["flickering_bonus"]
        member.veil_ward.active = ward["active"]
        member.veil_ward.source = ward["source"]
        member.concentration.spell_id = conc["spell_id"]
        # patron_id is per-member: read from the joiner's OWN row (mirrors dm_session's primary read).
        divine_favor = row.get("divine_favor") or {}
        member.patron_id = divine_favor.get("patron", "none")
        # corruption_level is NOT DB-persisted — it is runtime location-derived (movement_tools.py's
        # LOCATION_CORRUPTION). A joining player enters the party's room, so they are co-located;
        # adopt the party's current location corruption rather than a default 0.
        member.corruption_level = userdata.party.primary.corruption_level
        logger.info("Party-join: appended %r; party now %s", pid, userdata.party.member_ids)
