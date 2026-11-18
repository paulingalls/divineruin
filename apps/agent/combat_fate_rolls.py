"""Prepared combat rolls shared by the phase's continuation owners."""

from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass

import zhael_fate
from check_resolution import D20CheckCore, D20Roll
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

    async def save(self, session, checkpoint, roller_id, effect, roll, *, queries, conn):
        if "save" in checkpoint:
            fields = dict(checkpoint.pop("save"))
            d20 = D20Roll(**fields.pop("d20"))
            fields["consumed_conditions"] = tuple(fields["consumed_conditions"])
            original = SavingThrowResult(**fields, d20=d20)
            kept = self.select(d20.evaluate(original.roll))
            return _save_result(original, kept, effect)
        original = roll()
        if not session.fate_lock.locked():
            return original
        d20 = original.d20
        if d20 is not None and await self.hold(
            session, "save", roller_id, d20.evaluate(original.roll), d20, queries=queries, conn=conn
        ):
            stored = asdict(original)
            stored["consumed_conditions"] = list(original.consumed_conditions)
            checkpoint["save"] = stored
            return None
        return original
