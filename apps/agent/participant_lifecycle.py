"""Room participant lifecycle wiring for the DM session (extracted from agent.py to keep it
focused and under the module-size limit).

Two setup functions register LiveKit ``room.on`` handlers over a live session's participants:

- ``_setup_reconnection`` — disconnect/grace-timeout/reconnect for the PRIMARY player (any agent
  type). A drop pauses the session's background process and arms a grace timeout; a reconnect
  within the grace window resumes and re-greets.
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
import db_queries
from caster_state import ConcentrationState, ResonanceTrack
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
        if userdata.background:
            userdata.background.pause()
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
        if userdata.background:
            userdata.background.resume()
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


class PartyLifecycle:
    def __init__(
        self,
        room: rtc.Room,
        userdata: SessionData,
        *,
        queries,
        resonance_mod,
        concentration_mod,
    ) -> None:
        self.room = room
        self.userdata = userdata
        self.queries = queries
        self.resonance_mod = resonance_mod
        self.concentration_mod = concentration_mod
        self._live: dict[str, int] = {}
        self._last_generation: dict[str, int] = {}
        self._pending_joins: dict[str, asyncio.Task[None]] = {}
        self._join_failures: dict[str, tuple[int, BaseException]] = {}

        room.on("participant_connected", self._on_connected)
        room.on("participant_disconnected", self._on_disconnected)
        for participant in list(room.remote_participants.values()):
            self._on_connected(participant)

    def current_generation(self, identity: str) -> int | None:
        return self._live.get(identity)

    def is_authorized(self, identity: str, generation: int) -> bool:
        return self.userdata.party.contains(identity) and self._live.get(identity) == generation

    async def authorize(self, identity: str) -> int | None:
        generation = self._live.get(identity)
        if generation is None:
            return None
        pending = self._pending_joins.get(identity)
        if pending is not None:
            try:
                await pending
            except Exception as exc:
                raise RuntimeError(f"party hydration failed for {identity!r}") from exc
        failure = self._join_failures.get(identity)
        if failure is not None and failure[0] == generation:
            raise RuntimeError(f"party hydration failed for {identity!r}") from failure[1]
        if self._live.get(identity) != generation or not self.userdata.party.contains(identity):
            return None
        return generation

    def _on_connected(self, participant: rtc.RemoteParticipant) -> None:
        identity = participant.identity
        if not identity or identity in self._live:
            return
        generation = self._last_generation.get(identity, 0) + 1
        self._last_generation[identity] = generation
        self._join_failures.pop(identity, None)
        self._live[identity] = generation
        if self.userdata.party.contains(identity):
            return
        task = asyncio.create_task(self._hydrate_member(identity, generation))
        self._pending_joins[identity] = task
        task.add_done_callback(lambda completed, pid=identity, gen=generation: self._join_finished(pid, gen, completed))

    def _on_disconnected(self, participant: rtc.RemoteParticipant) -> None:
        self._live.pop(participant.identity, None)

    def _join_finished(self, identity: str, generation: int, task: asyncio.Task[None]) -> None:
        if self._pending_joins.get(identity) is task:
            self._pending_joins.pop(identity, None)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            self._join_failures[identity] = (generation, error)
            logger.error(
                "Party-join hydration failed for %r",
                identity,
                exc_info=(type(error), error, error.__traceback__),
            )

    async def _hydrate_member(self, identity: str, generation: int) -> None:
        row = await self.queries.get_player(identity)
        if row is None:
            if self._live.get(identity) == generation:
                self._live.pop(identity, None)
            logger.warning("Party-join: no players row for %r; skipping append", identity)
            return
        if self.userdata.party.contains(identity):
            return
        member = PartyMember(
            player_id=identity,
            resonance=ResonanceTrack(),
            concentration=ConcentrationState(),
        )
        self.userdata.party.members.append(member)
        res = await self.resonance_mod.read_player_resonance(identity)
        conc = await self.concentration_mod.read_player_concentration(identity)
        member.resonance.current = res["current"]
        member.resonance.flickering_bonus = res["flickering_bonus"]
        member.concentration.spell_id = conc["spell_id"]
        divine_favor = row.get("divine_favor") or {}
        member.patron_id = divine_favor.get("patron", "none")
        member.corruption_level = self.userdata.party.primary.corruption_level
        logger.info("Party-join: appended %r; party now %s", identity, self.userdata.party.member_ids)


def _setup_party_join(
    room: rtc.Room,
    userdata: SessionData,
    *,
    queries=db_queries,
    resonance_mod=db_mutations_resonance,
    concentration_mod=db_mutations_concentration,
) -> PartyLifecycle:
    return PartyLifecycle(
        room,
        userdata,
        queries=queries,
        resonance_mod=resonance_mod,
        concentration_mod=concentration_mod,
    )
