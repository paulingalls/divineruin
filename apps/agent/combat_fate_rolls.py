"""Prepared combat rolls shared by the phase's continuation owners."""

from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, replace

import db_queries
import encounter_facts
import oath_justice
import oath_timed
import zhael_fate
from check_resolution import D20CheckCore, D20Roll, SkillCheckResult, skill_with_roll
from check_resolution_save import SavingThrowResult, _save_result


@dataclass(frozen=True)
class PendingRoll:
    kind: str
    roller_id: str
    original: D20CheckCore
    d20: D20Roll
    candidates: zhael_fate.Candidates

    def offer(self, resume: Callable[[D20CheckCore], Awaitable[zhael_fate.Resumed]]) -> zhael_fate.FateOffer:
        offer = zhael_fate.make_offer(
            self.kind,
            self.roller_id,
            self.original,
            self.candidates,
            numbers=lambda roll: (roll.roll, roll.total),
            reroll=self.d20.roll,
            flip=self.d20.evaluate,
            resume=resume,
        )
        assert offer is not None
        return offer


@dataclass
class PhaseRolls:
    kept: D20CheckCore | None = None
    pending: PendingRoll | None = None

    def select(self, original: D20CheckCore) -> D20CheckCore:
        result = self.kept or original
        self.kept = None
        return result

    async def hold(self, session, kind, roller_id, original, d20, *, queries, conn, candidates=None) -> bool:
        if candidates is None:
            candidates = await zhael_fate.candidates(session, queries=queries, conn=conn)
        if not candidates.choices(roller_id, original.roll):
            return False
        assert self.kept is None and self.pending is None
        self.pending = PendingRoll(kind, roller_id, original, d20, candidates)
        return True

    async def save(self, session, checkpoint, roller_id, effect, roll, *, queries, conn, state=None, round_number=None):
        if "save" in checkpoint:
            original = saved_throw(checkpoint.pop("save"))
            d20 = original.d20
            assert d20 is not None
            kept = self.select(d20.evaluate(original.roll))
            return _save_result(original, kept, effect)
        original = await _prepare_save(
            session, state, roller_id, effect, roll, queries=queries, conn=conn, round_number=round_number
        )
        if not session.fate_lock.locked():
            return original
        d20 = original.d20
        if d20 is not None and await self.hold(
            session, "save", roller_id, d20.evaluate(original.roll), d20, queries=queries, conn=conn
        ):
            checkpoint["save"] = store_throw(original)
            return None
        return original


@dataclass(frozen=True)
class PacketRolls:
    phase: PhaseRolls
    steps: dict
    queries: object
    conn: object
    deescalation_round: int | None = None
    originating_participant_id: str | None = None

    @property
    def paused(self) -> bool:
        return self.phase.pending is not None

    def scope(self, name: str) -> "PacketRolls":
        return replace(self, steps=self.steps.setdefault(name, {}))

    def with_origin(self, participant_id: str) -> "PacketRolls":
        return replace(self, originating_participant_id=participant_id)

    async def save(self, session, roller_id, effect, roll, *, state):
        return await self.phase.save(
            session, self.steps, roller_id, effect, roll, queries=self.queries, conn=self.conn, state=state
        )

    def take_skill(self):
        if "skill" not in self.steps:
            return None
        fields = dict(self.steps.pop("skill"))
        d20 = D20Roll(**fields.pop("d20"))
        fields["consumed_conditions"] = tuple(fields["consumed_conditions"])
        original = SkillCheckResult(**fields, d20=d20)
        return skill_with_roll(original, self.phase.select(d20.evaluate(original.roll)))

    async def skill(self, session, roller_id, roll):
        if (kept := self.take_skill()) is not None:
            return kept
        original = await roll()
        d20 = original.d20 if session.fate_lock.locked() else None
        if d20 is not None and await self.phase.hold(
            session, "skill", roller_id, d20.evaluate(original.roll), d20, queries=self.queries, conn=self.conn
        ):
            stored = asdict(original)
            stored["consumed_conditions"] = list(original.consumed_conditions)
            self.steps["skill"] = stored
            return None
        return original


async def _prepare_save(session, state, roller_id, effect, roll, *, queries, conn, player=None, round_number=None):
    result = roll()
    if state is None and player is None:
        if result.originating_participant_id is not None and session.combat_state is not None:
            raise ValueError("Sourced combat save requires its working combat state")
        return result
    roller = state.get_participant(roller_id) if state is not None else None
    if player is None and roller is not None and roller.type == "player":
        player = await queries.get_player(roller_id, conn=conn)
        if player is None:
            raise ValueError(f"Missing authoritative player {roller_id!r}")
    result = await oath_justice.prepare_save(
        session, state, roller_id, result, effect, queries=queries, conn=conn, player=player
    )
    return oath_timed.prepare_save(state, roller_id, result, effect, player=player, round_number=round_number)


async def packet_save(
    progress,
    session,
    roller_id,
    effect,
    roll,
    *,
    state=None,
    queries=db_queries,
    conn=None,
    player=None,
):
    if progress is None:
        result = await _prepare_save(session, state, roller_id, effect, roll, queries=queries, conn=conn, player=player)
    else:
        result = await progress.save(session, roller_id, effect, roll, state=state)
    if result is not None and state is not None:
        encounter_facts.consume_rally(state, roller_id, result.rally_sources)
    return result


def store_throw(result: SavingThrowResult) -> dict:
    fields = asdict(result)
    fields["consumed_conditions"] = list(result.consumed_conditions)
    fields["rally_sources"] = list(result.rally_sources)
    return fields


def saved_throw(data: dict) -> SavingThrowResult:
    fields = dict(data)
    d20 = fields.pop("d20")
    fields["consumed_conditions"] = tuple(fields["consumed_conditions"])
    fields["rally_sources"] = tuple(fields.get("rally_sources", ()))
    return SavingThrowResult(**fields, d20=D20Roll(**d20) if d20 is not None else None)
