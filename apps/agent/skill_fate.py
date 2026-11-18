"""Authorization and settlement for session-held skill rolls."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import db
import db_queries
import zhael_fate
from check_resolution import SkillCheckResult, skill_with_roll
from session_data import SessionData


class StaleSkillOperation(Exception):
    """A held operation lost a precondition while awaiting its choice."""


@dataclass(frozen=True)
class SkillScope:
    roller_id: str
    origin: str
    primary_id: str
    party_ids: tuple[str, ...]
    combat_id: str | None

    @classmethod
    def capture(cls, session: SessionData, roller_id: str, *, party: bool = False) -> "SkillScope":
        return cls(
            roller_id,
            session.location_id,
            session.primary_player_id,
            tuple(sorted(session.party.member_ids)) if party else (),
            session.combat_state.combat_id if session.combat_state is not None else None,
        )

    @classmethod
    def restored(cls, data: dict) -> "SkillScope":
        return cls(data["roller_id"], data["origin"], data["primary_id"], tuple(data["party_ids"]), data["combat_id"])

    def validate(self, session: SessionData) -> None:
        if self.roller_id == session.departing_player_id or self.roller_id not in session.present_member_ids:
            raise StaleSkillOperation("The roller is no longer present.")
        if session.location_id != self.origin:
            raise StaleSkillOperation("The party left the original location.")
        combat = session.combat_state
        if self.combat_id != (combat.combat_id if combat is not None else None):
            raise StaleSkillOperation("The combat encounter changed.")
        if self.party_ids and (
            self.primary_id != session.primary_player_id or self.party_ids != tuple(sorted(session.party.member_ids))
        ):
            raise StaleSkillOperation("The party roster changed.")

    def validate_location(self, player_id: str, player: dict) -> None:
        if player.get("location_id") != self.origin:
            raise StaleSkillOperation(f"{player_id} is no longer at the original location.")

    async def lock_roller(self, session: SessionData, conn, *, queries=db_queries) -> dict:
        player = await queries.get_player(self.roller_id, conn=conn, for_update=True)
        self.validate(session)
        if player is None:
            raise StaleSkillOperation("The original roller no longer exists.")
        self.validate_location(self.roller_id, player)
        return player


async def prepare_skill_offer(
    session: SessionData,
    scope: SkillScope,
    roll: SkillCheckResult,
    player: dict,
    write: Callable[[SkillCheckResult, object], Awaitable[Callable[[], Awaitable[dict]]]],
    *,
    conn=None,
    queries=db_queries,
    db_mod=db,
) -> zhael_fate.FateOffer | None:
    d20 = roll.d20
    if d20 is None or not session.fate_lock.locked():
        return None
    candidates = await zhael_fate.candidates(session, queries=queries, conn=conn, roller=(scope.roller_id, player))

    async def resume(kept: SkillCheckResult) -> zhael_fate.Resumed:
        async with session.combat_state_lock:
            try:
                scope.validate(session)
                async with db_mod.transaction() as write_conn:
                    flush = await write(kept, write_conn)
                    scope.validate(session)
            except StaleSkillOperation as error:
                return zhael_fate.cancel(session, str(error))
            zhael_fate.effects_committed(session)
            return zhael_fate.Resumed(await flush())

    return zhael_fate.make_offer(
        "skill",
        scope.roller_id,
        roll,
        candidates,
        numbers=lambda result: (result.roll, result.total),
        reroll=lambda: skill_with_roll(roll, d20.roll()),
        flip=lambda face: skill_with_roll(roll, d20.evaluate(face)),
        resume=resume,
    )
