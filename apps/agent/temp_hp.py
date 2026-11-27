"""Player temporary HP and the shared damage calculation."""

from typing import TYPE_CHECKING, NamedTuple

import asyncpg

if TYPE_CHECKING:
    from combat_participant import CombatParticipant


def validate(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"temp_hp must be a nonnegative integer, got {value!r}")
    return value


def from_player(player: dict) -> int:
    return validate(player.get("temp_hp", 0))


def player_pool(participant: "CombatParticipant") -> int:
    return participant.temp_hp if participant.type == "player" else 0


def beast_pool(participant: "CombatParticipant") -> int:
    form = participant.wild_shape if participant.type == "player" else None
    return form["hp_current"] if form is not None else 0


class Damage(NamedTuple):
    hp: int
    temporary: int
    absorbed: int
    overkill: int
    beast: int
    beast_absorbed: int
    carryover: int

    def receipt(self, gift: dict) -> dict:
        facts = {**gift, "temp_hp_absorbed": self.absorbed, "temp_hp_remaining": self.temporary}
        cues = [gift.get("dm_cue", "")]
        if self.absorbed:
            cues.append(f"Temporary HP absorbed {self.absorbed} damage.")
        if self.beast_absorbed:
            facts.update(
                beast_hp_absorbed=self.beast_absorbed, beast_hp_remaining=self.beast, carryover_damage=self.carryover
            )
            cues.append(f"Beast HP absorbed {self.beast_absorbed} damage.")
            if self.beast == 0:
                cues.append(f"The beast form dropped. {self.carryover} damage carried over.")
        if cue := " ".join(filter(None, cues)):
            facts["dm_cue"] = cue
        return facts


def absorb(damage: int, hp: int, temporary: int, *, beast: int = 0, hp_floor: int = 0) -> Damage:
    absorbed = min(temporary, damage)
    beast_absorbed = min(beast, damage - absorbed)
    carryover = damage - absorbed - beast_absorbed
    remaining = hp - carryover
    return Damage(
        max(hp_floor, remaining),
        temporary - absorbed,
        absorbed,
        max(0, -remaining) if not hp_floor else 0,
        beast - beast_absorbed,
        beast_absorbed,
        carryover,
    )


async def grant(
    player_id: str,
    locked_player: dict,
    amount: int,
    *,
    participant: "CombatParticipant | None" = None,
    conn: asyncpg.Connection,
) -> tuple[int, int]:
    """Grant to a locked player row and its transaction's working participant."""
    from db_mutations import update_player_temp_hp

    if participant is not None and (participant.type != "player" or participant.id != player_id):
        raise ValueError("Temporary HP requires the matching player participant")
    before = from_player(locked_player)
    after = max(before, validate(amount))
    if after > before:
        await update_player_temp_hp(player_id, after, conn=conn)
        if participant is not None:
            participant.temp_hp = after
    return before, after
