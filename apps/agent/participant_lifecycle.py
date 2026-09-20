"""Room participant lifecycle wiring for the DM session (extracted from agent.py to keep it
focused and under the module-size limit).

Two setup functions register LiveKit ``room.on`` handlers over a live session's participants:

- ``_setup_reconnection`` — disconnect/grace-timeout/reconnect for the PRIMARY player (any agent
  type). A drop pauses the session's background process and arms a grace timeout; a reconnect
  within the grace window resumes and re-greets.
- ``_setup_party_join`` — the live multi-PC trigger (M18 story-001): a SECOND participant joining
  the room becomes a PartyMember with its own hydrated per-member state. It returns the
  ``PartyLifecycle`` that owns the party roster AND the per-connection authorization gate the
  transcription/input path asks before any player speech reaches the DM.

Both are wired by agent.dm_session; the party-join trigger is wired at gameplay start only.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

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


class ReconnectionLifecycle:
    def __init__(
        self,
        room: rtc.Room,
        session: AgentSession,
        userdata: SessionData,
        agent: Agent,
        *,
        sleep: Callable[[float], Awaitable[None]],
    ) -> None:
        self.room = room
        self.session = session
        self.userdata = userdata
        self.agent = agent
        self.sleep = sleep
        self._deadline: asyncio.Task[None] | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self.close_task: asyncio.Task[None] | None = None
        self._closing_from_grace = False
        self._closed = False
        room.on("participant_disconnected", self._on_disconnect)
        room.on("participant_connected", self._on_reconnect)
        session.on("close", self._on_session_close)

    def _on_session_close(self, _event: object) -> None:
        if self.close_task is None:
            self.close_task = asyncio.create_task(self.aclose())

    def _on_disconnect(self, participant: rtc.RemoteParticipant) -> None:
        if participant.identity != self.userdata.player_id or self.userdata.player_disconnected:
            return
        self.userdata.player_disconnected = True
        self.userdata.disconnect_time = time.time()
        if self.userdata.background:
            self.userdata.background.pause()
        self._deadline = asyncio.create_task(self._grace_timeout())
        self._tasks.add(self._deadline)

    def _on_reconnect(self, participant: rtc.RemoteParticipant) -> None:
        if participant.identity != self.userdata.player_id or not self.userdata.player_disconnected:
            return
        self.userdata.player_disconnected = False
        deadline = self._deadline
        self._deadline = None
        task = asyncio.create_task(self._finish_reconnect(deadline))
        self._tasks.add(task)

    async def _finish_reconnect(self, deadline: asyncio.Task[None] | None) -> None:
        if deadline is not None:
            deadline.cancel()
            try:
                await deadline
            except asyncio.CancelledError:
                pass
        if self.userdata.player_disconnected:
            return
        if self.userdata.background:
            self.userdata.background.resume()
        reconnect_reply = self.session.generate_reply(instructions=_build_reconnect_instruction(self.userdata))
        fire = getattr(self.agent, "_fire_and_forget", None)
        if fire:
            fire(reconnect_reply)

    async def _grace_timeout(self) -> None:
        await self.sleep(RECONNECT_GRACE_S)
        logger.info("Reconnect grace period expired for %s", self.userdata.player_id)
        self._closing_from_grace = True
        try:
            await self.session.aclose()
        finally:
            self._closing_from_grace = False

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.room.off("participant_disconnected", self._on_disconnect)
        self.room.off("participant_connected", self._on_reconnect)
        self.session.off("close", self._on_session_close)
        current = asyncio.current_task()
        # LiveKit emits close inside the grace task's session.aclose(); canceling that task
        # here would cancel the session close that triggered this cleanup.
        tasks = tuple(
            task
            for task in self._tasks
            if task is not current and not (task is self._deadline and self._closing_from_grace)
        )
        for task in tasks:
            if not task.done():
                task.cancel()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        failures = [result for result in results if isinstance(result, Exception)]
        if failures:
            raise BaseExceptionGroup("reconnection cleanup failed", failures)


def _setup_reconnection(
    room: rtc.Room,
    session: AgentSession,
    userdata: SessionData,
    agent: Agent,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> ReconnectionLifecycle:
    return ReconnectionLifecycle(room, session, userdata, agent, sleep=sleep)


class PartyLifecycle:
    """The room's party membership, and the authorization gate over it (M18 story-001).

    Membership is PERSISTENT: a PartyMember appended here survives a disconnect, because the
    party is the campaign's roster, not the room's attendance. Authorization is not — each
    live connection for an identity gets a monotonic *generation*, so a transcript captured
    before a drop cannot speak for the identity that reconnected behind it.

    ``queries`` + the read-helper modules are injectable so a MagicMock-room unit test can
    supply AsyncMocks.
    """

    def __init__(
        self,
        room: rtc.Room,
        userdata: SessionData,
        *,
        queries: Any,
        resonance_mod: Any,
        concentration_mod: Any,
    ) -> None:
        self.room = room
        self.userdata = userdata
        self.queries = queries
        self.resonance_mod = resonance_mod
        self.concentration_mod = concentration_mod
        self._live: dict[str, int] = {}
        self._last_generation: dict[str, int] = {}
        self._revocations: dict[tuple[str, int], asyncio.Event] = {}
        self._pending_joins: dict[str, asyncio.Task[None]] = {}
        # Retain a strong reference to EVERY spawned join task until it finishes. asyncio only
        # holds a weak reference, so an unreferenced create_task() can be garbage-collected
        # mid-await — silently dropping the member append/hydrate (a fail-silent violation of
        # the fail-loud rule). _pending_joins alone is not that reference: a reconnect while a
        # join is still in flight overwrites its entry under the same identity.
        self._spawned_joins: set[asyncio.Task[None]] = set()
        self._join_failures: dict[str, tuple[int, BaseException]] = {}
        self._closed = False

        room.on("participant_connected", self._on_connected)
        room.on("participant_disconnected", self._on_disconnected)
        for participant in list(room.remote_participants.values()):
            self._on_connected(participant)

    def current_generation(self, identity: str) -> int | None:
        return self._live.get(identity)

    def is_authorized(self, identity: str, generation: int) -> bool:
        return self.userdata.party.contains(identity) and self._live.get(identity) == generation

    async def wait_until_revoked(self, identity: str, generation: int) -> None:
        if self._live.get(identity) != generation:
            return
        await self._revocations[(identity, generation)].wait()

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
        if identity in self._live:
            return
        generation = self._last_generation.get(identity, 0) + 1
        self._last_generation[identity] = generation
        self._join_failures.pop(identity, None)
        self._live[identity] = generation
        self._revocations[(identity, generation)] = asyncio.Event()
        if self.userdata.party.contains(identity):
            return
        task = asyncio.create_task(self._hydrate_member(identity, generation))
        self._pending_joins[identity] = task
        self._spawned_joins.add(task)
        task.add_done_callback(self._spawned_joins.discard)
        task.add_done_callback(lambda completed, pid=identity, gen=generation: self._join_finished(pid, gen, completed))

    def _on_disconnected(self, participant: rtc.RemoteParticipant) -> None:
        self._revoke(participant.identity)

    def _revoke(self, identity: str) -> None:
        generation = self._live.pop(identity, None)
        if generation is not None:
            self._revocations[(identity, generation)].set()

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.room.off("participant_connected", self._on_connected)
        self.room.off("participant_disconnected", self._on_disconnected)
        for identity in tuple(self._live):
            self._revoke(identity)
        for task in self._spawned_joins:
            if not task.done():
                task.cancel()
        results = await asyncio.gather(*self._spawned_joins, return_exceptions=True)
        self._spawned_joins.clear()
        failures = [result for result in results if isinstance(result, Exception)]
        if failures:
            raise BaseExceptionGroup("party lifecycle cleanup failed", failures)

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
            # Boundary/external-input case: a stray participant with no players row must NOT
            # fail-loud the whole room (unlike combat_init's internal-SSOT fail-loud). Drop its
            # live generation so nothing it says can ever be authorized, then log + skip.
            if self._live.get(identity) == generation:
                self._revoke(identity)
            logger.warning("Party-join: no players row for %r; skipping append", identity)
            return
        # Race guard: a second participant_connected for the same identity may have appended
        # during the await above.
        if self.userdata.party.contains(identity):
            return
        member = PartyMember(
            player_id=identity,
            resonance=ResonanceTrack(),
            concentration=ConcentrationState(),
        )
        self.userdata.party.members.append(member)  # IN PLACE — never reassign userdata.party (f4f16c93076e)

        # Hydrate the per-member sub-states the same way session_hydration.hydrate_session_state
        # applies them onto the primary. The veil ward is NOT among them (M24 story-004): it is
        # scope-owned, so a joiner resolves the ward already covering the party's location and a
        # per-member read could only ever disagree with the scope.
        res = await self.resonance_mod.read_player_resonance(identity)
        conc = await self.concentration_mod.read_player_concentration(identity)
        member.resonance.current = res["current"]
        member.resonance.flickering_bonus = res["flickering_bonus"]
        member.concentration.spell_id = conc["spell_id"]
        # patron_id is per-member: read from the joiner's OWN row (mirrors dm_session's primary read).
        divine_favor = row.get("divine_favor") or {}
        member.patron_id = divine_favor.get("patron", "none")
        # corruption_level is NOT DB-persisted — it is runtime location-derived (movement_tools.py's
        # LOCATION_CORRUPTION). A joining player enters the party's room, so adopt the party's
        # current location corruption rather than a default 0.
        member.corruption_level = self.userdata.party.primary.corruption_level
        logger.info("Party-join: appended %r; party now %s", identity, self.userdata.party.member_ids)


def _setup_party_join(
    room: rtc.Room,
    userdata: SessionData,
    *,
    queries: Any = db_queries,
    resonance_mod: Any = db_mutations_resonance,
    concentration_mod: Any = db_mutations_concentration,
) -> PartyLifecycle:
    return PartyLifecycle(
        room,
        userdata,
        queries=queries,
        resonance_mod=resonance_mod,
        concentration_mod=concentration_mod,
    )
